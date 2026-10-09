"""Edges of the plugin: settings, the server check, the marker, frozen clocks and subtests."""

import json
import math
import ssl
import time
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
import requests
import responses

from pytest_mailpit import MailpitAssertionError, MailpitClient, MailpitConfig
from pytest_mailpit.plugin import _CONFIG, _FAILED, _record
from tests import samples
from tests.test_waiting import page

URL = "http://localhost:8025/"
MESSAGES = f"{URL}api/v1/messages"


# Settings


def test_the_help_shows_even_when_a_setting_is_wrong(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILPIT_URL", "localhost:8025")  # no scheme

    result = pytester.runpytest("--help")

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*--mailpit-url=URL*"])


def test_a_container_and_a_url_on_the_command_line_do_not_go_together(
    pytester: pytest.Pytester,
) -> None:
    result = pytester.runpytest("--mailpit-container", "--mailpit-url", "http://mailpit.test/")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--mailpit-container * cannot go with --mailpit-url*"])


@pytest.mark.parametrize(
    ("env", "args", "header"),
    [
        ({"MAILPIT_URL": "http://env.test/"}, [], "mailpit: http://env.test/"),
        ({}, ["--mailpit-url", "http://cli.test/"], "mailpit: http://cli.test/"),
        (
            {"MAILPIT_URL": "http://env.test/"},
            ["--mailpit-container"],
            "mailpit: a Docker container of axllent/mailpit, started on first use",
        ),
    ],
    ids=["environment over ini", "command line over ini", "command line over environment"],
)
def test_an_explicit_url_wins_over_the_ini_files_container(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    args: list[str],
    header: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile("def test_nothing(): pass")

    pytester.runpytest(*args).stdout.fnmatch_lines([header])


def test_the_smtp_server_is_on_the_host_of_the_url(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A CI service named "mailpit", for example.
    monkeypatch.setenv("MAILPIT_URL", "http://mailpit:8025/")
    pytester.makepyfile(
        "def test_smtp(mailpit_config): assert tuple(mailpit_config.smtp) == ('mailpit', 1025)"
    )

    pytester.runpytest().assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("ini", "env", "args", "message"),
    [
        ("", {"MAILPIT_VERIFY": "flase"}, [], "*mailpit_verify must be true, false or the path*"),
        ("", {}, ["--mailpit-timeout", "nan"], "*must be a positive number of seconds*"),
        ("mailpit_poll_interval = nan", {}, [], "*must be a positive number of seconds*"),
    ],
    ids=["mistyped verify", "nan timeout", "nan poll interval"],
)
def test_settings_that_cannot_work_stop_the_run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    ini: str,
    env: dict[str, str],
    args: list[str],
    message: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile("def test_nothing(): pass")

    result = pytester.runpytest(*args)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([message])


def test_the_client_refuses_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="wait_timeout must not be negative, got nan"):
        MailpitClient(URL, wait_timeout=math.nan)
    with pytest.raises(ValueError, match="poll_interval must be positive, got nan"):
        MailpitClient(URL, poll_interval=math.nan)


# The marker


@pytest.mark.parametrize(
    ("marker", "given"),
    [
        ("mailpit(30)", "mailpit(30)"),
        ("mailpit(timout=30)", "mailpit(timout=30)"),
        ("mailpit(timeout=float('nan'))", None),
    ],
)
def test_a_marker_that_would_be_ignored_stops_the_run(
    pytester: pytest.Pytester, marker: str, given: str | None
) -> None:
    pytester.makepyfile(
        f"""
        import pytest

        @pytest.mark.{marker}
        def test_slow(mailpit_inbox_factory):
            pass
        """
    )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(MESSAGES, json=samples.MESSAGE_LIST)
        result = pytester.runpytest()

    expected = (
        f"*@pytest.mark.mailpit takes only timeout=<seconds>, got {given}*"
        if given
        else "*@pytest.mark.mailpit(timeout=...) must be a number of seconds, got nan*"
    )
    result.stdout.fnmatch_lines([expected])


# The server check


def _check_with(pytester: pytest.Pytester, ini: str = "", **answer: object) -> pytest.RunResult:
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(MESSAGES, **answer)
        return pytester.runpytest("-rs")


def test_a_tls_error_fails_even_where_unreachable_mailpit_is_skipped(
    pytester: pytest.Pytester,
) -> None:
    error = requests.exceptions.SSLError(ssl.SSLCertVerificationError("certificate verify failed"))

    result = _check_with(pytester, "mailpit_unreachable = skip", body=error)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*failed TLS verification*Set MAILPIT_VERIFY to the CA file of its certificate*"]
    )


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_proxy_without_mailpit_behind_it_counts_as_unreachable(
    pytester: pytest.Pytester, status: int
) -> None:
    result = _check_with(pytester, "mailpit_unreachable = skip", status=status, body="Bad Gateway")

    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines([f"*the server in front of it answered HTTP {status}*"])


def test_wrong_credentials_are_called_wrong(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILPIT_USERNAME", "qa")
    monkeypatch.setenv("MAILPIT_PASSWORD", "wrong")

    result = _check_with(pytester, status=401, body="Unauthorised")

    result.stdout.fnmatch_lines(["*rejected the username and password in MAILPIT_USERNAME*"])


# A failed subtest


def test_a_failure_stays_when_a_later_report_passes() -> None:
    # pytest-subtests reports a failed subtest, then the test itself as passed.
    config = SimpleNamespace(stash=pytest.Stash())
    config.stash[_CONFIG] = MailpitConfig()
    item = SimpleNamespace(stash=pytest.Stash(), config=config, nodeid="t.py::test_x")

    _record(item, SimpleNamespace(when="call", failed=True))  # type: ignore[arg-type]
    _record(item, SimpleNamespace(when="call", failed=False))  # type: ignore[arg-type]

    assert item.stash[_FAILED]


# A frozen clock


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """time.monotonic() stands still, as under freezegun's freeze_time; time.sleep is real."""
    monkeypatch.setattr("pytest_mailpit.client.time.monotonic", lambda: 1000.0)


@pytest.fixture
def empty_mailpit() -> Iterator[None]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/search", json=page())
        mock.get(MESSAGES, json=page())
        mock.get(f"{URL}api/v1/chaos", status=400, body=json.dumps("Chaos is not enabled"))
        yield


@pytest.mark.usefixtures("frozen_clock", "empty_mailpit")
def test_waits_end_under_a_frozen_clock() -> None:
    client = MailpitClient(URL, poll_interval=0.05)
    started = time.perf_counter()

    with pytest.raises(MailpitAssertionError, match=r"within 0\.2s, none arrived"):
        client.wait_for_message(subject="Hello", timeout=0.2)
    client.assert_no_message(subject="Hello", within=0.2)

    assert time.perf_counter() - started < 5
