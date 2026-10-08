"""The plugin, run in an inner pytest session (pytester) against a mocked Mailpit."""

import json
import re
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses
from requests import PreparedRequest

from tests import samples
from tests.test_waiting import page, summary

URL = "http://localhost:8025/"
SEARCH = re.compile(re.escape(f"{URL}api/v1/search") + r"\?.*")
MESSAGE = re.compile(re.escape(f"{URL}api/v1/message/") + r"[^/]+$")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inner sessions read MAILPIT_* variables; those of the machine must not leak in."""
    for name in (
        "MAILPIT_URL",
        "MAILPIT_USERNAME",
        "MAILPIT_PASSWORD",
        "MAILPIT_VERIFY",
        "MAILPIT_WAIT_TIMEOUT",
        "PYTEST_XDIST_WORKER",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server() -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit at the default URL, holding one message for every inbox."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        mock.add_callback(responses.GET, SEARCH, callback=_one_message_per_address)
        mock.get(MESSAGE, json=samples.MESSAGE)
        mock.get(f"{URL}api/v1/messages", json=page())
        mock.delete(f"{URL}api/v1/messages", body="ok")
        yield mock


def _one_message_per_address(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
    query = parse_qs(urlsplit(request.url or "").query)["query"][0]
    address = re.search(r'addressed:"([^"]+)"', query)
    found = [summary(f"id-{address.group(1)}", to=address.group(1))] if address else []
    return 200, {"Content-Type": "application/json"}, json.dumps(page(*found))


def deleted_ids(server: responses.RequestsMock) -> list[str]:
    bodies = [call.request.body for call in server.calls if call.request.method == "DELETE"]
    return [message_id for body in bodies for message_id in json.loads(body or "{}")["IDs"]]


# Registration


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("mailpit")


def test_plugin_can_be_disabled(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_disabled(pytestconfig):
            assert not pytestconfig.pluginmanager.has_plugin("mailpit")
        """
    )

    result = pytester.runpytest("-p", "no:mailpit")

    result.assert_outcomes(passed=1)


def test_report_header_shows_the_url_without_credentials(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile("def test_nothing(): pass")

    result = pytester.runpytest("--mailpit-url", "http://user:secret@mailpit.test:8025/")

    result.stdout.fnmatch_lines(["mailpit: http://mailpit.test:8025/"])
    assert "secret" not in result.stdout.str()


# Settings


def test_defaults(pytester: pytest.Pytester, server: responses.RequestsMock) -> None:
    pytester.makepyfile(
        """
        from pytest_mailpit import MailpitConfig

        def test_config(mailpit_config):
            assert mailpit_config == MailpitConfig()
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)


def test_ini_settings(pytester: pytest.Pytester, server: responses.RequestsMock) -> None:
    pytester.makeini(
        """
        [pytest]
        mailpit_url = http://mailpit.test:8025/mailpit/
        mailpit_verify = /etc/ssl/ca.pem
        mailpit_wait_timeout = 30
        mailpit_poll_interval = 0.25
        mailpit_domain = shop.test
        mailpit_keep_on_failure = false
        mailpit_unreachable = skip
        """
    )
    pytester.makepyfile(
        """
        from pytest_mailpit import MailpitConfig

        def test_config(mailpit_config):
            assert mailpit_config == MailpitConfig(
                url="http://mailpit.test:8025/mailpit/",
                verify="/etc/ssl/ca.pem",
                wait_timeout=30,
                poll_interval=0.25,
                domain="shop.test",
                keep_on_failure=False,
                skip_if_unreachable=True,
            )
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("env", "args", "expected_url", "expected_timeout"),
    [
        ({}, [], "http://ini.test/", 30.0),
        (
            {"MAILPIT_URL": "http://env.test/", "MAILPIT_WAIT_TIMEOUT": "20"},
            [],
            "http://env.test/",
            20.0,
        ),
        (
            {"MAILPIT_URL": "http://env.test/", "MAILPIT_WAIT_TIMEOUT": "20"},
            ["--mailpit-url", "http://cli.test/", "--mailpit-timeout", "5"],
            "http://cli.test/",
            5.0,
        ),
    ],
)
def test_command_line_beats_environment_beats_ini(
    pytester: pytest.Pytester,
    server: responses.RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    args: list[str],
    expected_url: str,
    expected_timeout: float,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    pytester.makeini("[pytest]\nmailpit_url = http://ini.test/\nmailpit_wait_timeout = 30\n")
    pytester.makepyfile(
        f"""
        def test_config(mailpit_config):
            assert mailpit_config.url == {expected_url!r}
            assert mailpit_config.wait_timeout == {expected_timeout!r}
        """
    )

    pytester.runpytest(*args).assert_outcomes(passed=1)


def test_credentials_and_tls_come_from_the_environment(
    pytester: pytest.Pytester, server: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILPIT_USERNAME", "qa")
    monkeypatch.setenv("MAILPIT_PASSWORD", "secret")
    monkeypatch.setenv("MAILPIT_VERIFY", "false")
    pytester.makepyfile(
        """
        def test_config(mailpit_config):
            assert (mailpit_config.username, mailpit_config.password) == ("qa", "secret")
            assert mailpit_config.verify is False
            assert "secret" not in repr(mailpit_config)
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("ini", "args", "message"),
    [
        ("", ["--mailpit-timeout", "soon"], "mailpit wait timeout must be a number of seconds"),
        ("", ["--mailpit-timeout", "-1"], "mailpit wait timeout must be a positive number"),
        ("mailpit_poll_interval = 0", [], "mailpit_poll_interval must be a positive number"),
        ("mailpit_unreachable = maybe", [], "mailpit_unreachable must be fail or skip"),
        ("mailpit_domain = a@b.test", [], "mailpit_domain must be a domain"),
        ("", ["--mailpit-url", "localhost:8025"], "must start with http:// or https://"),
    ],
)
def test_invalid_settings_stop_the_run(
    pytester: pytest.Pytester,
    server: responses.RequestsMock,
    ini: str,
    args: list[str],
    message: str,
) -> None:
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile("def test_nothing(): pass")

    result = pytester.runpytest(*args)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([f"*{message}*"])


@pytest.mark.parametrize(("value", "expected"), [("yes", True), ("0", False)])
def test_tls_verification_words(
    pytester: pytest.Pytester,
    server: responses.RequestsMock,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("MAILPIT_VERIFY", value)
    pytester.makepyfile(
        f"def test_config(mailpit_config): assert mailpit_config.verify is {expected}"
    )

    pytester.runpytest().assert_outcomes(passed=1)


# The mailpit fixture


def test_unreachable_mailpit_fails_with_what_to_do(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")

    with responses.RequestsMock() as mock:
        refused = requests.ConnectionError("[Errno 111] Connection refused")
        mock.get(f"{URL}api/v1/info", body=refused)
        result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*ERROR at setup of test_needs_mailpit*",
            "Cannot reach Mailpit at http://localhost:8025/ ([[]Errno 111] Connection refused).",
            "Start Mailpit, for example: docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit",
            "or point pytest-mailpit at it with --mailpit-url or MAILPIT_URL.",
            "*short test summary info*",
        ],
        consecutive=True,
    )


def test_a_multi_line_cause_is_cut_to_its_first_line(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")

    # Nothing is registered: the mock refuses with a message of several lines.
    with responses.RequestsMock():
        result = pytester.runpytest()

    result.stdout.fnmatch_lines(
        ["Cannot reach Mailpit at http://localhost:8025/ (Connection refused by Responses*)."]
    )
    assert "Available matches" not in result.stdout.str()


def test_unreachable_mailpit_can_skip_the_tests(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmailpit_unreachable = skip\n")
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass\ndef test_other(): pass")

    with responses.RequestsMock():
        result = pytester.runpytest("-rs")

    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*Cannot reach Mailpit*"])


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "*requires a username and password: set MAILPIT_USERNAME and MAILPIT_PASSWORD.*"),
        (500, "*cannot be used: GET http://localhost:8025/api/v1/info returned HTTP 500*"),
    ],
)
def test_mailpit_answering_with_an_error(
    pytester: pytest.Pytester, status: int, message: str
) -> None:
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")

    with responses.RequestsMock() as mock:
        mock.get(f"{URL}api/v1/info", status=status, body="nope")
        result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([message])
    assert "During handling of the above exception" not in result.stdout.str()


def test_old_mailpit_versions_get_a_warning(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")

    with responses.RequestsMock() as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO | {"Version": "v1.20.3"})
        result = pytester.runpytest()

    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(["*Mailpit v1.20.3 is older than 1.22*"])


def test_the_client_is_shared_by_the_session(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        clients = []

        def test_one(mailpit):
            clients.append(mailpit)

        def test_two(mailpit):
            assert clients == [mailpit]
            assert mailpit.wait_timeout == 10
        """
    )

    pytester.runpytest().assert_outcomes(passed=2)
    info_calls = [call for call in server.calls if call.request.url == f"{URL}api/v1/info"]
    assert len(info_calls) == 1


# Inboxes


def test_inbox_waits_for_its_message_and_cleans_up(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        import re

        def test_reset(mailpit_inbox):
            address = r"pytest-[0-9a-f]{6}-[0-9a-f]{8}@example\\.com"
            assert re.fullmatch(address, mailpit_inbox.address)
            message = mailpit_inbox.wait_for_message(subject="Hello")
            assert message.subject == "Поръчка №1001"
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)

    [deleted] = deleted_ids(server)
    assert re.fullmatch(r"id-pytest-[0-9a-f]{6}-[0-9a-f]{8}@example\.com", deleted)


def test_factory_creates_separate_inboxes_and_cleans_up_all(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        def test_invite(mailpit_inbox, mailpit_inbox_factory):
            guest = mailpit_inbox_factory()
            assert guest.address != mailpit_inbox.address
            assert guest.address.split("-")[1] == mailpit_inbox.address.split("-")[1]
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)

    assert len(deleted_ids(server)) == 2


def test_a_failed_test_keeps_its_messages_and_shows_them(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        def test_fails(mailpit_inbox):
            assert False, "the link was wrong"
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    assert deleted_ids(server) == []
    result.stdout.fnmatch_lines(
        [
            "*Mailpit messages to pytest-*@example.com*",
            "Messages to pytest-*@example.com (1):",
            "*Received (UTC)*To*Subject",
            "*11:22:33*pytest-*@example.com*Hello",
            "Mailpit: http://localhost:8025/",
        ]
    )


def test_a_failed_test_can_delete_its_messages(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makeini("[pytest]\nmailpit_keep_on_failure = false\n")
    pytester.makepyfile("def test_fails(mailpit_inbox): assert False")

    pytester.runpytest().assert_outcomes(failed=1)

    assert len(deleted_ids(server)) == 1


def test_failure_report_survives_mailpit_going_away(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_fails(mailpit_inbox): assert False")

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["Could not list the messages to pytest-*: Cannot reach Mailpit*"])


def test_cleanup_failures_are_warnings(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_passes(mailpit_inbox): pass")

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        mock.add_callback(responses.GET, SEARCH, callback=_one_message_per_address)
        mock.delete(f"{URL}api/v1/messages", status=500, body="disk full")
        result = pytester.runpytest()

    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(["*Could not delete the messages to pytest-*disk full*"])


def test_inbox_domain_comes_from_the_settings(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makeini("[pytest]\nmailpit_domain = shop.test\n")
    pytester.makepyfile(
        "def test_domain(mailpit_inbox): assert mailpit_inbox.address.endswith('@shop.test')"
    )

    pytester.runpytest().assert_outcomes(passed=1)


# The marker


def test_marker_sets_the_inbox_timeout(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.mailpit(timeout=30)
        def test_slow_email(mailpit_inbox):
            assert mailpit_inbox.wait_timeout == 30

        def test_default(mailpit_inbox):
            assert mailpit_inbox.wait_timeout == 10
        """
    )

    pytester.runpytest("--strict-markers").assert_outcomes(passed=2)


@pytest.mark.parametrize("timeout", ["'soon'", "-1", "True"])
def test_marker_timeout_must_be_seconds(
    pytester: pytest.Pytester, server: responses.RequestsMock, timeout: str
) -> None:
    pytester.makepyfile(
        f"""
        import pytest

        @pytest.mark.mailpit(timeout={timeout})
        def test_slow_email(mailpit_inbox):
            pass
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*mailpit(timeout=...) must be a number of seconds*"])


def test_marker_without_timeout_uses_the_default(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.mailpit
        def test_marked(mailpit_inbox):
            assert mailpit_inbox.wait_timeout == 10
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)
