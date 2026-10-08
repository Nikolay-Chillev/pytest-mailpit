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
Tag failed messages                                                      ``mailpit_tag_failures``
Report failed messages                                                   ``mailpit_report_messages``
When unreachable                                                         ``mailpit_unreachable``
SMTP host:port                                 ``MAILPIT_SMTP``          ``mailpit_smtp``
Start a container      ``--mailpit-container``                           ``mailpit_container``
Container image                                                          ``mailpit_container_image``
=====================  ======================  ========================  ==========================
"""

import dataclasses
import os
import re
import warnings
from collections.abc import Callable, Generator, Iterator, Mapping
from typing import Any
from urllib.parse import urlsplit

import pytest

from pytest_mailpit._container import start_container, testcontainers_installed
from pytest_mailpit._django import email_settings
from pytest_mailpit._http import _without_credentials
from pytest_mailpit._reporting import failure_tag, report_failure
from pytest_mailpit.aio import AsyncInbox, AsyncMailpitClient
from pytest_mailpit.chaos import Chaos
from pytest_mailpit.client import MailpitClient
from pytest_mailpit.config import DEFAULT_DOMAIN, DEFAULT_IMAGE, MailpitConfig, SMTPServer
from pytest_mailpit.errors import (
    MailpitAPIError,
    MailpitConnectionError,
    MailpitError,
    MailpitWarning,
)
from pytest_mailpit.inbox import Inbox, unique_address
from pytest_mailpit.models import ChaosTriggers

# The oldest Mailpit version pytest-mailpit is tested against.
OLDEST_SUPPORTED_VERSION = (1, 22)
# Unless started with another MP_MAX_MESSAGES, Mailpit keeps the newest 500
# messages and deletes the others every minute.
MAILPIT_DEFAULT_MAX_MESSAGES = 500

_CONFIG = pytest.StashKey[MailpitConfig]()
_REPORTS = pytest.StashKey[dict[str, pytest.TestReport]]()
_INBOXES = pytest.StashKey[list[Inbox]]()
# Whether a failed test kept its messages in Mailpit.
_KEPT = pytest.StashKey[bool]()


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
        "--mailpit-container",
        dest="mailpit_container",
        action="store_true",
        default=None,
        help="Start Mailpit in a Docker container for the session (needs Testcontainers).",
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
        "mailpit_tag_failures",
        "Tag the messages a failed test kept with the test's name, to find them in Mailpit.",
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
        "mailpit_smtp",
        "Host and port of Mailpit's SMTP server, for mailpit_smtp (default: localhost:1025).",
        default="",
    )
    parser.addini(
        "mailpit_container",
        "Start Mailpit in a Docker container for the session (needs Testcontainers).",
        type="bool",
        default=False,
    )
    parser.addini(
        "mailpit_container_image",
        f"Docker image of the Mailpit container (default: {DEFAULT_IMAGE}).",
        default="",
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
    container = bool(config.getoption("mailpit_container") or config.getini("mailpit_container"))
    if container and not testcontainers_installed():
        raise pytest.UsageError(
            "mailpit_container needs Testcontainers: pip install 'pytest-mailpit[testcontainers]'"
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
        tag_failures=bool(config.getini("mailpit_tag_failures")),
        report_messages=bool(config.getini("mailpit_report_messages")),
        skip_if_unreachable=unreachable == "skip",
        smtp=_smtp(setting(None, "MAILPIT_SMTP", "mailpit_smtp"), defaults.smtp),
        container=container,
        container_image=setting(None, None, "mailpit_container_image") or defaults.container_image,
    )


def pytest_report_header(config: pytest.Config) -> str:
    mailpit_config = config.stash[_CONFIG]
    if mailpit_config.container:
        return (
            f"mailpit: a Docker container of {mailpit_config.container_image}, started on first use"
        )
    return f"mailpit: {_without_credentials(mailpit_config.url)}"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    _record(item, report)
    return report


def _record(item: pytest.Item, report: pytest.TestReport) -> None:
    """Remember the report for the inbox teardown; tag and report a failed test's messages."""
    item.stash.setdefault(_REPORTS, {})[report.when] = report
    inboxes = item.stash.get(_INBOXES, [])
    if report.when != "call" or not report.failed or not inboxes:
        return
    config = item.config.stash[_CONFIG]
    # Tags only help find messages that are kept.
    tag = failure_tag(item.nodeid) if config.keep_on_failure and config.tag_failures else None
    if tag is not None or config.report_messages:
        report_failure(
            item.config, report, inboxes, tag=tag, report_messages=config.report_messages
        )


# Fixtures


@pytest.fixture(scope="session")
def mailpit_config(pytestconfig: pytest.Config, request: pytest.FixtureRequest) -> MailpitConfig:
    """The settings pytest-mailpit runs with.

    With ``mailpit_container``, the URL and SMTP server are the container's.
    """
    config = pytestconfig.stash[_CONFIG]
    if not config.container:
        return config
    container = request.getfixturevalue("mailpit_container")
    return dataclasses.replace(
        config,
        url=f"{container.get_base_api_url()}/",
        smtp=SMTPServer(container.get_container_host_ip(), int(container.get_exposed_smtp_port())),
    )


@pytest.fixture(scope="session")
def mailpit_container(pytestconfig: pytest.Config) -> Iterator[Any]:
    """Mailpit in a Docker container for the session, with ``mailpit_container = true``.

    It is Testcontainers' MailpitContainer, started with Chaos enabled and
    without reverse DNS lookups. Under pytest-xdist every worker gets its own.
    """
    config = pytestconfig.stash[_CONFIG]
    problem = None
    if not config.container:
        problem = (
            "The mailpit_container fixture needs mailpit_container = true, or --mailpit-container."
        )
    else:
        try:
            container = start_container(config.container_image)
        except Exception as error:  # Docker not running, image missing, ...
            problem = (
                f"Could not start Mailpit in a Docker container ({_root_cause(error)}). "
                "Is Docker running?"
            )
    # Fail outside the except block, so pytest does not print the chain of Docker errors.
    if problem is not None:
        pytest.fail(problem, pytrace=False)
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mailpit_smtp(mailpit_config: MailpitConfig) -> SMTPServer:
    """Host and port of Mailpit's SMTP server: where the application under test sends email."""
    return mailpit_config.smtp


@pytest.fixture(scope="session")
def mailpit(mailpit_config: MailpitConfig, pytestconfig: pytest.Config) -> Iterator[MailpitClient]:
    """A MailpitClient for the configured server, checked to be reachable.

    If Mailpit cannot be reached, the tests that use it fail with what to do
    about it, or are skipped with ``mailpit_unreachable = skip``.
    """
    client = mailpit_config.client()
    try:
        _check_server(client, mailpit_config)
        yield client
        # A container goes away with the session, and the kept messages with it.
        if pytestconfig.stash.get(_KEPT, False) and not mailpit_config.container:
            _warn_if_nearly_full(client)
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
        if created:
            request.config.stash[_KEPT] = True
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


@pytest.fixture(scope="session")
def mailpit_async(mailpit: MailpitClient) -> AsyncMailpitClient:
    """The mailpit client for async tests: every method that asks Mailpit is awaited."""
    return AsyncMailpitClient(mailpit)


@pytest.fixture
def mailpit_async_inbox(mailpit_inbox: Inbox) -> AsyncInbox:
    """mailpit_inbox for async tests: the same address and cleanup, with methods to await.

    Waiting yields to the event loop, so an application that sends the email
    from the same loop keeps running.
    """
    return AsyncInbox(mailpit_inbox)


@pytest.fixture
def mailpit_django(mailpit: MailpitClient, mailpit_smtp: SMTPServer) -> Iterator[None]:
    """Django sends the test's email over SMTP to Mailpit, instead of keeping it in memory.

    Django's test runner, and pytest-django, put sent email in
    ``django.core.mail.outbox``. With this fixture it reaches Mailpit as a
    recipient would get it, for mailpit_inbox and the checks on messages.
    """
    try:
        import django
        from django.conf import settings
        from django.test.utils import override_settings
    except ImportError:
        missing = True
    else:
        missing = False
    if missing:
        pytest.fail("mailpit_django needs Django: pip install django", pytrace=False)
    mailers = getattr(settings, "MAILERS", None)
    with override_settings(**email_settings(django.VERSION, mailers, mailpit_smtp)):
        yield


@pytest.fixture
def mailpit_chaos(mailpit: MailpitClient, mailpit_config: MailpitConfig) -> Iterator[Chaos]:
    """Makes Mailpit's SMTP server reject messages, to test how the application handles it.

    Mailpit must run with Chaos enabled: ``MP_ENABLE_CHAOS=true``, or
    ``mailpit_container = true``. The errors apply to every message Mailpit
    receives; after the test, the triggers Mailpit had before are restored.
    """
    original = _chaos_triggers(mailpit)
    if os.environ.get("PYTEST_XDIST_WORKER") and not mailpit_config.container:
        warnings.warn(
            "mailpit_chaos makes Mailpit reject the messages of every pytest-xdist worker, "
            "not only this test's. Give each worker its own Mailpit with "
            "mailpit_container = true, or run the Chaos tests in a run without -n.",
            MailpitWarning,
            stacklevel=1,
        )
    yield Chaos(mailpit)
    try:
        mailpit.set_chaos(original)
    except MailpitError as error:
        warnings.warn(
            f"Could not restore Mailpit's Chaos triggers, so it may still reject messages: {error}",
            MailpitWarning,
            stacklevel=1,
        )


# Helpers


def _check_server(client: MailpitClient, config: MailpitConfig) -> None:
    # Fail outside the except blocks: failing inside one makes pytest print the
    # whole chain of requests and urllib3 exceptions above the message.
    unreachable = problem = None
    try:
        # Not /api/v1/info: it makes Mailpit ask GitHub for its latest release first,
        # which takes up to 10 s where outbound connections hang (see MailpitClient.info).
        client.messages(limit=1)
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
    _warn_if_too_old(client)


def _warn_if_too_old(client: MailpitClient) -> None:
    """Warn about a Mailpit older than the oldest version pytest-mailpit supports.

    Mailpit 1.22 added /api/v1/chaos, so an older one answers 404 there. Its
    version number is only in /api/v1/info, which is slow (see _check_server).
    """
    try:
        client.chaos()
    except MailpitAPIError as error:
        if error.status_code == 404:
            oldest = ".".join(map(str, OLDEST_SUPPORTED_VERSION))
            warnings.warn(
                f"Mailpit at {client.url} is older than {oldest}, the oldest version "
                "pytest-mailpit is tested with; some features may not work.",
                MailpitWarning,
                stacklevel=1,
            )
    except MailpitError:
        pass  # 400 means Chaos is off; anything else is for the tests to report


def _chaos_triggers(client: MailpitClient) -> ChaosTriggers:
    try:
        return client.chaos()
    except MailpitAPIError as error:
        if error.status_code == 400:  # "Chaos is not enabled"
            problem = (
                f"mailpit_chaos needs Chaos enabled in Mailpit at {client.url}: start Mailpit "
                "with MP_ENABLE_CHAOS=true or --enable-chaos, or use mailpit_container = true."
            )
        elif error.status_code == 404:
            problem = f"mailpit_chaos needs Mailpit 1.22 or newer at {client.url}."
        else:
            raise
    # Fail outside the except block, so pytest does not print the API error above the message.
    pytest.fail(problem, pytrace=False)


def _warn_if_nearly_full(client: MailpitClient) -> None:
    """Warn when Mailpit may soon delete the messages that failed tests kept."""
    try:
        held = client.messages(limit=1).total
    except MailpitError:
        return  # Mailpit went away; the failed tests already said what they could.
    if held >= MAILPIT_DEFAULT_MAX_MESSAGES * 0.9:
        warnings.warn(
            f"Mailpit at {client.url} holds {held} messages. With its default limit of "
            f"{MAILPIT_DEFAULT_MAX_MESSAGES} (MP_MAX_MESSAGES), it deletes the oldest every "
            "minute, so the messages kept from failed tests may soon be gone. Delete old "
            "messages, or start Mailpit with a higher MP_MAX_MESSAGES (0 for no limit).",
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


def _smtp(value: str | None, default: SMTPServer) -> SMTPServer:
    if value is None:
        return default
    try:
        parts = urlsplit(f"//{value.strip()}")
        host, port = parts.hostname, parts.port
    except ValueError:
        host = port = None
    if not host or not port:
        raise pytest.UsageError(f"The Mailpit SMTP server must be host:port, got {value!r}")
    return SMTPServer(host, port)


def _verify(value: str | None, default: bool | str) -> bool | str:
    if value is None:
        return default
    if value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off"):
        return False
    return value  # a CA bundle
