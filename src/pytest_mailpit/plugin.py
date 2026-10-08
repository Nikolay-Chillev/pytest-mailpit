"""The pytest plugin, registered through the ``pytest11`` entry point as ``mailpit``.

Disable it for a run with ``-p no:mailpit``.

Settings, highest priority first: command line option, environment variable,
ini setting, default.

=====================  ======================  ========================  ==========================
Setting                Option                  Environment               ini
=====================  ======================  ========================  ==========================
URL of Mailpit         ``--mailpit-url``       ``MAILPIT_URL``           ``mailpit_url``
UI username/password                           ``MAILPIT_USERNAME``,
                                               ``MAILPIT_PASSWORD``
TLS verification                               ``MAILPIT_VERIFY``        ``mailpit_verify``
Wait timeout (s)       ``--mailpit-timeout``   ``MAILPIT_WAIT_TIMEOUT``  ``mailpit_wait_timeout``
Poll interval (s)                                                        ``mailpit_poll_interval``
Inbox domain                                                             ``mailpit_domain``
Keep failed messages                                                     ``mailpit_keep_on_failure``
Report failed messages                                                   ``mailpit_report_messages``
When unreachable                                                         ``mailpit_unreachable``
=====================  ======================  ========================  ==========================
"""

import os
import re
import warnings
from collections.abc import Callable, Generator, Iterator, Mapping

import pytest

from pytest_mailpit._http import _without_credentials
from pytest_mailpit._reporting import report_failure
from pytest_mailpit.client import MailpitClient
from pytest_mailpit.config import DEFAULT_DOMAIN, MailpitConfig
from pytest_mailpit.errors import (
    MailpitAPIError,
    MailpitConnectionError,
    MailpitError,
    MailpitWarning,
)
from pytest_mailpit.inbox import Inbox, unique_address

# The oldest Mailpit version pytest-mailpit is tested against.
OLDEST_SUPPORTED_VERSION = (1, 22)

_CONFIG = pytest.StashKey[MailpitConfig]()
_REPORTS = pytest.StashKey[dict[str, pytest.TestReport]]()
_INBOXES = pytest.StashKey[list[Inbox]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("mailpit", "testing emails with Mailpit")
    group.addoption(
        "--mailpit-url",
        dest="mailpit_url",
        metavar="URL",
        help="URL of Mailpit's web UI, with its web root if it has one "
        "(default: http://localhost:8025/).",
    )
    group.addoption(
        "--mailpit-timeout",
        dest="mailpit_wait_timeout",
        metavar="SECONDS",
        help="How long to wait for an email (default: 10).",
    )
    parser.addini("mailpit_url", "URL of Mailpit's web UI.", default="")
    parser.addini(
        "mailpit_verify", "Verify Mailpit's TLS certificate: true, false or a CA file.", default=""
    )
    parser.addini("mailpit_wait_timeout", "How long to wait for an email, in seconds.", default="")
    parser.addini(
        "mailpit_poll_interval", "How often to check for an email, in seconds.", default=""
    )
    parser.addini(
        "mailpit_domain",
        f"Domain of mailpit_inbox addresses (default: {DEFAULT_DOMAIN}).",
        default="",
    )
    parser.addini(
        "mailpit_keep_on_failure",
        "Keep the messages of a failed test in Mailpit.",
        type="bool",
        default=True,
    )
    parser.addini(
        "mailpit_report_messages",
        "List a failed test's messages in its report, and attach them to Allure and pytest-html.",
        type="bool",
        default=True,
    )
    parser.addini(
        "mailpit_unreachable",
        "What happens to tests that need Mailpit when it cannot be reached: fail or skip.",
        default="fail",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "mailpit(timeout=None): settings of pytest-mailpit for one test; "
        "timeout is how long mailpit_inbox waits for an email.",
    )
    config.stash[_CONFIG] = load_config(config, os.environ)


def load_config(config: pytest.Config, environ: Mapping[str, str]) -> MailpitConfig:
    """Read the settings; invalid values stop the run with a usage error."""

    def setting(option: str | None, env: str | None, ini: str | None) -> str | None:
        if option is not None and (value := config.getoption(option)) is not None:
            return str(value)
        if env is not None and (value := environ.get(env)):
            return value
        if ini is not None and (value := config.getini(ini)):
            return str(value)
        return None

    defaults = MailpitConfig()
    unreachable = str(config.getini("mailpit_unreachable")).strip().lower()
    if unreachable not in ("fail", "skip"):
        raise pytest.UsageError(f"mailpit_unreachable must be fail or skip, got {unreachable!r}")
    url = setting("mailpit_url", "MAILPIT_URL", "mailpit_url") or defaults.url
    if not re.match(r"https?://[^/]", url):
        raise pytest.UsageError(f"The Mailpit URL must start with http:// or https://, got {url!r}")
    domain = setting(None, None, "mailpit_domain") or defaults.domain
    if "@" in domain or not domain.strip():
        raise pytest.UsageError(
            f"mailpit_domain must be a domain such as example.com, got {domain!r}"
        )
    return MailpitConfig(
        url=url,
        username=environ.get("MAILPIT_USERNAME") or None,
        password=environ.get("MAILPIT_PASSWORD") or None,
        verify=_verify(setting(None, "MAILPIT_VERIFY", "mailpit_verify"), defaults.verify),
        wait_timeout=_seconds(
            "mailpit wait timeout",
            setting("mailpit_wait_timeout", "MAILPIT_WAIT_TIMEOUT", "mailpit_wait_timeout"),
            defaults.wait_timeout,
            allow_zero=True,
        ),
        poll_interval=_seconds(
            "mailpit_poll_interval",
            setting(None, None, "mailpit_poll_interval"),
            defaults.poll_interval,
            allow_zero=False,
        ),
        domain=domain.strip(),
        keep_on_failure=bool(config.getini("mailpit_keep_on_failure")),
        report_messages=bool(config.getini("mailpit_report_messages")),
        skip_if_unreachable=unreachable == "skip",
    )


def pytest_report_header(config: pytest.Config) -> str:
    return f"mailpit: {_without_credentials(config.stash[_CONFIG].url)}"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    _record(item, report)
    return report


def _record(item: pytest.Item, report: pytest.TestReport) -> None:
    """Remember the report for the inbox teardown, and add the inbox's messages to failures."""
    item.stash.setdefault(_REPORTS, {})[report.when] = report
    inboxes = item.stash.get(_INBOXES, [])
    if (
        report.when == "call"
        and report.failed
        and inboxes
        and item.config.stash[_CONFIG].report_messages
    ):
        report_failure(item.config, report, inboxes)


# Fixtures


@pytest.fixture(scope="session")
def mailpit_config(pytestconfig: pytest.Config) -> MailpitConfig:
    """The settings pytest-mailpit runs with."""
    return pytestconfig.stash[_CONFIG]


@pytest.fixture(scope="session")
def mailpit(mailpit_config: MailpitConfig) -> Iterator[MailpitClient]:
    """A MailpitClient for the configured server, checked to be reachable.

    If Mailpit cannot be reached, the tests that use it fail with what to do
    about it, or are skipped with ``mailpit_unreachable = skip``.
    """
    client = mailpit_config.client()
    try:
        _check_server(client, mailpit_config)
        yield client
    finally:
        client.close()


@pytest.fixture
def mailpit_inbox_factory(
    mailpit: MailpitClient, mailpit_config: MailpitConfig, request: pytest.FixtureRequest
) -> Iterator[Callable[[], Inbox]]:
    """Creates inboxes for the test: call it once for each address the test needs.

    After the test, the messages sent to the inboxes are deleted, unless the
    test failed and ``mailpit_keep_on_failure`` is on (the default).
    """
    created: list[Inbox] = []
    timeout = _marker_timeout(request.node) or mailpit_config.wait_timeout
    worker = os.environ.get("PYTEST_XDIST_WORKER")

    def create() -> Inbox:
        address = unique_address(request.node.nodeid, domain=mailpit_config.domain, worker=worker)
        inbox = Inbox(mailpit, address, wait_timeout=timeout)
        created.append(inbox)
        request.node.stash.setdefault(_INBOXES, []).append(inbox)
        return inbox

    yield create

    reports = request.node.stash.get(_REPORTS, {})
    if mailpit_config.keep_on_failure and any(report.failed for report in reports.values()):
        return
    for inbox in created:
        try:
            inbox.clear()
        except MailpitError as error:
            warnings.warn(
                f"Could not delete the messages to {inbox.address}: {error}",
                MailpitWarning,
                stacklevel=1,
            )


@pytest.fixture
def mailpit_inbox(mailpit_inbox_factory: Callable[[], Inbox]) -> Inbox:
    """A unique email address for this test, and the messages sent to it."""
    return mailpit_inbox_factory()


# Helpers


def _check_server(client: MailpitClient, config: MailpitConfig) -> None:
    # Fail outside the except blocks: failing inside one makes pytest print the
    # whole chain of requests and urllib3 exceptions above the message.
    unreachable = problem = None
    try:
        info = client.info()
    except MailpitConnectionError as error:
        unreachable = (
            f"Cannot reach Mailpit at {client.url} ({_root_cause(error)}).\n"
            "Start Mailpit, for example: docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit\n"
            "or point pytest-mailpit at it with --mailpit-url or MAILPIT_URL."
        )
    except MailpitAPIError as error:
        if error.status_code == 401:
            problem = (
                f"Mailpit at {client.url} requires a username and password: "
                "set MAILPIT_USERNAME and MAILPIT_PASSWORD."
            )
        else:
            problem = f"Mailpit at {client.url} cannot be used: {error}"
    if unreachable is not None:
        if config.skip_if_unreachable:
            pytest.skip(unreachable)
        pytest.fail(unreachable, pytrace=False)
    if problem is not None:
        pytest.fail(problem, pytrace=False)
    version = _version(info.version)
    if version is not None and version < OLDEST_SUPPORTED_VERSION:
        oldest = ".".join(map(str, OLDEST_SUPPORTED_VERSION))
        warnings.warn(
            f"Mailpit {info.version} is older than {oldest}, the oldest version "
            "pytest-mailpit is tested with; some features may not work.",
            MailpitWarning,
            stacklevel=1,
        )


def _root_cause(error: BaseException) -> str:
    """The first line of the innermost cause of an error, e.g. "[Errno 111] Connection refused"."""
    while error.__cause__ is not None or error.__context__ is not None:
        error = error.__cause__ or error.__context__  # type: ignore[assignment]
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _marker_timeout(node: pytest.Item | pytest.Collector) -> float | None:
    marker = node.get_closest_marker("mailpit")
    if marker is None or marker.kwargs.get("timeout") is None:
        return None
    timeout = marker.kwargs["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout < 0:
        raise pytest.UsageError(
            f"@pytest.mark.mailpit(timeout=...) must be a number of seconds, got {timeout!r}"
        )
    return float(timeout)


def _seconds(name: str, value: str | None, default: float, *, allow_zero: bool) -> float:
    if value is None:
        return default
    try:
        seconds = float(value)
    except ValueError:
        raise pytest.UsageError(f"{name} must be a number of seconds, got {value!r}") from None
    if seconds < 0 or (seconds == 0 and not allow_zero):
        raise pytest.UsageError(f"{name} must be a positive number of seconds, got {value!r}")
    return seconds


def _verify(value: str | None, default: bool | str) -> bool | str:
    if value is None:
        return default
    if value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off"):
        return False
    return value  # a CA bundle


def _version(version: str) -> tuple[int, ...] | None:
    match = re.match(r"v?(\d+)\.(\d+)", version)
    return tuple(int(part) for part in match.groups()) if match else None
