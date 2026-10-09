"""Chaos: the client's API calls, the Chaos helper and the mailpit_chaos fixture."""

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
import responses
from requests import PreparedRequest

from pytest_mailpit import (
    Chaos,
    ChaosTrigger,
    ChaosTriggers,
    MailpitAPIError,
    MailpitAssertionError,
    MailpitClient,
)
from tests import samples
from tests.test_waiting import page

URL = "http://localhost:8025/"
CHAOS = f"{URL}api/v1/chaos"
DEFAULT_CODES = {"Sender": 451, "Recipient": 451, "Authentication": 535}

Response = tuple[int, dict[str, str], str]


class FakeChaos:
    """Mailpit's Chaos API: it keeps the triggers and fills in default error codes."""

    def __init__(self) -> None:
        self.enabled = True
        self.status: int | None = None  # answer every request with this error status
        self.failing_puts_after: int | None = None
        self.puts: list[dict[str, Any]] = []
        self.triggers: dict[str, dict[str, int]] = {
            name: {"ErrorCode": code, "Probability": 0} for name, code in DEFAULT_CODES.items()
        }

    def get(self, request: PreparedRequest) -> Response:
        return self.error() or (200, {}, json.dumps(self.triggers))

    def put(self, request: PreparedRequest) -> Response:
        if self.failing_puts_after is not None and len(self.puts) >= self.failing_puts_after:
            return 500, {}, "database is locked"
        if error := self.error():
            return error
        body = json.loads(request.body or "{}")
        self.puts.append(body)
        for name, code in DEFAULT_CODES.items():
            trigger = body.get(name) or {}
            self.triggers[name] = {
                "ErrorCode": trigger.get("ErrorCode") or code,
                "Probability": trigger.get("Probability") or 0,
            }
        return 200, {}, json.dumps(self.triggers)

    def error(self) -> Response | None:
        if self.status is not None:
            return self.status, {}, "something went wrong"
        if not self.enabled:
            return 400, {}, "Chaos is not enabled"
        return None


@pytest.fixture
def fake() -> Iterator[FakeChaos]:
    fake = FakeChaos()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/messages", json=samples.MESSAGE_LIST)
        mock.get(re.compile(re.escape(f"{URL}api/v1/search") + ".*"), json=page())
        mock.add_callback(responses.GET, CHAOS, fake.get)
        mock.add_callback(responses.PUT, CHAOS, fake.put)
        yield fake


@pytest.fixture
def chaos(fake: FakeChaos) -> Chaos:
    return Chaos(MailpitClient(URL))


# The client


def test_chaos_reads_the_triggers(fake: FakeChaos) -> None:
    fake.triggers["Recipient"] = {"ErrorCode": 550, "Probability": 25}

    triggers = MailpitClient(URL).chaos()

    assert triggers == ChaosTriggers(recipient=ChaosTrigger(550, 25))
    assert triggers.active
    assert triggers.recipient.active
    assert not triggers.sender.active


def test_missing_triggers_get_mailpit_defaults() -> None:
    triggers = ChaosTriggers.from_api({"Sender": {"Probability": 10}})

    assert triggers == ChaosTriggers(sender=ChaosTrigger(451, 10))
    assert ChaosTriggers().authentication == ChaosTrigger(535, 0)
    assert not ChaosTriggers().active


def test_set_chaos_sends_every_trigger(fake: FakeChaos) -> None:
    applied = MailpitClient(URL).set_chaos(ChaosTriggers(sender=ChaosTrigger(421, 50)))

    assert fake.puts == [
        {
            "Sender": {"ErrorCode": 421, "Probability": 50},
            "Recipient": {"ErrorCode": 451, "Probability": 0},
            "Authentication": {"ErrorCode": 535, "Probability": 0},
        }
    ]
    assert applied == ChaosTriggers(sender=ChaosTrigger(421, 50))


def test_chaos_disabled_is_an_api_error(fake: FakeChaos) -> None:
    fake.enabled = False

    with pytest.raises(MailpitAPIError, match="Chaos is not enabled") as error:
        MailpitClient(URL).chaos()

    assert error.value.status_code == 400


# The Chaos helper


def test_each_rejection_keeps_the_other_triggers(fake: FakeChaos, chaos: Chaos) -> None:
    chaos.reject_senders(550, probability=30)
    chaos.reject_recipients()
    chaos.reject_authentication()

    assert chaos.triggers == ChaosTriggers(
        sender=ChaosTrigger(550, 30),
        recipient=ChaosTrigger(451, 100),
        authentication=ChaosTrigger(535, 100),
    )


def test_reset_turns_every_error_off(fake: FakeChaos, chaos: Chaos) -> None:
    chaos.reject_recipients(554)

    chaos.reset()

    assert chaos.triggers == ChaosTriggers()


@pytest.mark.parametrize(
    ("code", "probability", "problem"),
    [
        (250, 100, "code must be an SMTP error code from 400 to 599, got 250"),
        (600, 100, "code must be an SMTP error code from 400 to 599, got 600"),
        (451, 101, "probability must be a percentage from 0 to 100, got 101"),
        (451, -1, "probability must be a percentage from 0 to 100, got -1"),
    ],
)
def test_invalid_errors_never_reach_mailpit(
    fake: FakeChaos, chaos: Chaos, code: int, probability: int, problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        chaos.reject_recipients(code, probability=probability)

    assert fake.puts == []


def test_overlapping_chaos_tests_leave_mailpit_as_it_was(fake: FakeChaos) -> None:
    # Two pytest-xdist workers sharing one Mailpit: the second test starts while the
    # first one's error is on, so the error is part of what it found.
    client = MailpitClient(URL)
    first, second = Chaos(client), Chaos(client)
    before_first = client.chaos()
    first.reject_recipients(451)
    before_second = client.chaos()

    first._restore(before_first)
    second._restore(before_second)

    assert client.chaos() == ChaosTriggers()


def test_a_trigger_changed_since_is_left_alone(fake: FakeChaos, chaos: Chaos) -> None:
    client = MailpitClient(URL)
    before = client.chaos()
    chaos.reject_senders()
    another_test = ChaosTriggers(sender=ChaosTrigger(554, 100))
    client.set_chaos(another_test)

    chaos._restore(before)

    assert client.chaos() == another_test


def test_nothing_set_means_nothing_to_restore(fake: FakeChaos, chaos: Chaos) -> None:
    chaos._restore(ChaosTriggers(sender=ChaosTrigger(421, 5)))

    assert fake.puts == []


def test_a_timed_out_wait_says_that_chaos_rejects_messages(fake: FakeChaos) -> None:
    fake.triggers["Recipient"] = {"ErrorCode": 550, "Probability": 100}
    fake.triggers["Sender"] = {"ErrorCode": 451, "Probability": 30}

    with pytest.raises(MailpitAssertionError) as failure:
        MailpitClient(URL).wait_for_message(recipient="new@example.com", timeout=0)

    assert str(failure.value).endswith(
        "\nMailpit's Chaos is rejecting senders (451, 30%) and recipients (550, 100%), so the "
        "email may never have arrived. If a Chaos test left it on, turn it off with "
        "mailpit.set_chaos(ChaosTriggers())."
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_no_chaos_hint_when_chaos_rejects_nothing(fake: FakeChaos, enabled: bool) -> None:
    fake.enabled = enabled

    with pytest.raises(MailpitAssertionError) as failure:
        MailpitClient(URL).wait_for_message(recipient="new@example.com", timeout=0)

    assert "Chaos" not in str(failure.value)


def test_chaos_names_its_server(chaos: Chaos) -> None:
    assert repr(chaos) == "Chaos('http://localhost:8025/')"


# The mailpit_chaos fixture, in inner sessions


def test_the_fixture_restores_the_triggers_mailpit_had(
    pytester: pytest.Pytester, fake: FakeChaos
) -> None:
    # Started with MP_CHAOS_TRIGGERS, for example.
    fake.triggers["Sender"] = {"ErrorCode": 421, "Probability": 5}
    pytester.makepyfile(
        """
        from pytest_mailpit import ChaosTrigger

        def test_passes(mailpit_chaos):
            mailpit_chaos.reject_recipients(554)
            assert mailpit_chaos.triggers.recipient == ChaosTrigger(554, 100)

        def test_fails(mailpit_chaos):
            mailpit_chaos.reset()
            assert False
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, failed=1)
    assert fake.triggers["Sender"] == {"ErrorCode": 421, "Probability": 5}
    assert fake.triggers["Recipient"] == {"ErrorCode": 451, "Probability": 0}
    assert "MailpitWarning" not in result.stdout.str()


def test_chaos_not_enabled_fails_with_what_to_do(
    pytester: pytest.Pytester, fake: FakeChaos
) -> None:
    fake.enabled = False
    pytester.makepyfile("def test_chaos(mailpit_chaos): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "mailpit_chaos needs Chaos enabled in Mailpit at http://localhost:8025/: start "
            "Mailpit with MP_ENABLE_CHAOS=true or --enable-chaos, or use mailpit_container = true."
        ]
    )
    assert "During handling of the above exception" not in result.stdout.str()


def test_mailpit_without_chaos_fails_with_the_version_it_needs(
    pytester: pytest.Pytester, fake: FakeChaos
) -> None:
    fake.status = 404
    pytester.makepyfile("def test_chaos(mailpit_chaos): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["mailpit_chaos needs Mailpit 1.22 or newer at http://localhost:8025/."]
    )


def test_other_api_errors_are_raised(pytester: pytest.Pytester, fake: FakeChaos) -> None:
    fake.status = 500
    pytester.makepyfile("def test_chaos(mailpit_chaos): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*MailpitAPIError: GET*api/v1/chaos returned HTTP 500*"])


def test_parallel_workers_sharing_mailpit_get_a_warning(
    pytester: pytest.Pytester, fake: FakeChaos, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    pytester.makepyfile("def test_chaos(mailpit_chaos): pass")

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        ["*MailpitWarning: mailpit_chaos makes Mailpit reject the messages of every*"]
    )


def test_a_failed_restore_is_a_warning(pytester: pytest.Pytester, fake: FakeChaos) -> None:
    fake.failing_puts_after = 1
    pytester.makepyfile("def test_chaos(mailpit_chaos): mailpit_chaos.reject_senders()")

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        ["*Could not restore Mailpit's Chaos triggers, so it may still reject messages*"]
    )


@pytest.mark.parametrize(("code", "probability"), [(200, 100), (451, 150)])
def test_an_invalid_trigger_never_reaches_mailpit(
    fake: FakeChaos, code: int, probability: int
) -> None:
    # Mailpit applies the triggers one by one, so a bad one would leave the others changed.
    with pytest.raises(ValueError, match="must be"):
        MailpitClient(URL).set_chaos(ChaosTriggers(recipient=ChaosTrigger(code, probability)))

    assert fake.puts == []


def test_one_worker_alone_gets_no_warning(
    pytester: pytest.Pytester, fake: FakeChaos, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pytest -n 1, or -n auto on a runner with one CPU.
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "1")
    pytester.makepyfile("def test_chaos(mailpit_chaos): pass")

    pytester.runpytest().assert_outcomes(passed=1, warnings=0)
