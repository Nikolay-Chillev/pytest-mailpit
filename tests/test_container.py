"""mailpit_container and mailpit_smtp, in inner sessions with a fake Testcontainers."""

import json
import re
import sys
import types
from collections.abc import Iterator
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from requests import PreparedRequest

from pytest_mailpit import SMTPServer
from tests import samples
from tests.test_waiting import page, summary

URL = "http://localhost:8025/"


class FakeContainer:
    """Stands in for Testcontainers' MailpitContainer."""

    instances: ClassVar[list["FakeContainer"]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, image: str) -> None:
        self.image = image
        self.env: dict[str, str] = {}
        self.started = self.stopped = False
        FakeContainer.instances.append(self)

    def with_env(self, name: str, value: str) -> "FakeContainer":
        self.env[name] = value
        return self

    def start(self) -> "FakeContainer":
        if FakeContainer.fail_with is not None:
            raise FakeContainer.fail_with
        self.started = True
        return self

    def stop(self) -> None:
        self.stopped = True

    def get_base_api_url(self) -> str:
        return URL.rstrip("/")

    def get_container_host_ip(self) -> str:
        return "127.0.0.1"

    def get_exposed_smtp_port(self) -> int:
        return 32768


@pytest.fixture(autouse=True)
def fake_testcontainers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MAILPIT_URL", "MAILPIT_SMTP", "PYTEST_XDIST_WORKER"):
        monkeypatch.delenv(name, raising=False)
    module = types.ModuleType("testcontainers.community.mailpit")
    module.MailpitContainer = FakeContainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "testcontainers.community.mailpit", module)
    monkeypatch.setattr(FakeContainer, "instances", [])
    monkeypatch.setattr(FakeContainer, "fail_with", None)


@pytest.fixture
def mailpit_api() -> Iterator[responses.RequestsMock]:
    def search(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        query = parse_qs(urlsplit(request.url or "").query)["query"][0]
        address = re.search(r'addressed:"([^"]+)"', query)
        found = [summary("m1", to=address.group(1))] if address else []
        return 200, {"Content-Type": "application/json"}, json.dumps(page(*found))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        mock.add_callback(
            responses.GET, re.compile(re.escape(f"{URL}api/v1/search") + ".*"), search
        )
        mock.get(f"{URL}api/v1/message/m1", json=samples.MESSAGE | {"ID": "m1"})
        mock.delete(f"{URL}api/v1/messages", body="ok")
        yield mock


USES_THE_CONTAINER = """
from pytest_mailpit import SMTPServer

def test_one(mailpit_config, mailpit_smtp, mailpit_inbox):
    assert mailpit_config.url == "http://localhost:8025/"
    assert mailpit_smtp == SMTPServer("127.0.0.1", 32768)
    assert mailpit_inbox.wait_for_message().id == "m1"

def test_two(mailpit_inbox):
    pass
"""


def test_the_container_serves_the_whole_session(
    pytester: pytest.Pytester, mailpit_api: responses.RequestsMock
) -> None:
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile(USES_THE_CONTAINER)

    result = pytester.runpytest()

    result.assert_outcomes(passed=2)
    [container] = FakeContainer.instances
    assert container.image == "axllent/mailpit"
    assert container.env == {"MP_SMTP_DISABLE_RDNS": "true", "MP_ENABLE_CHAOS": "true"}
    assert container.started
    assert container.stopped
    result.stdout.fnmatch_lines(
        ["mailpit: a Docker container of axllent/mailpit, started on first use"]
    )


def test_the_command_line_and_the_image_setting(
    pytester: pytest.Pytester, mailpit_api: responses.RequestsMock
) -> None:
    pytester.makeini("[pytest]\nmailpit_container_image = axllent/mailpit:v1.31.4\n")
    pytester.makepyfile(USES_THE_CONTAINER)

    pytester.runpytest("--mailpit-container").assert_outcomes(passed=2)

    assert [container.image for container in FakeContainer.instances] == ["axllent/mailpit:v1.31.4"]


def test_no_container_is_started_until_a_test_needs_mailpit(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile("def test_unrelated(): pass")

    pytester.runpytest().assert_outcomes(passed=1)

    assert FakeContainer.instances == []


def test_without_testcontainers_the_run_stops_with_what_to_install(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "testcontainers.community.mailpit", None)
    monkeypatch.setitem(sys.modules, "testcontainers.mailpit", None)
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile("def test_nothing(): pass")

    result = pytester.runpytest()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*pip install 'pytest-mailpit[[]testcontainers]'*"])


def test_older_testcontainers_are_found_too(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, mailpit_api: responses.RequestsMock
) -> None:
    old = types.ModuleType("testcontainers.mailpit")
    old.MailpitContainer = FakeContainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "testcontainers.community.mailpit", None)
    monkeypatch.setitem(sys.modules, "testcontainers.mailpit", old)
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile(USES_THE_CONTAINER)

    pytester.runpytest().assert_outcomes(passed=2)


def test_docker_not_running_fails_with_a_short_message(pytester: pytest.Pytester) -> None:
    FakeContainer.fail_with = RuntimeError("Error while fetching server API version")
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile("def test_needs_mailpit(mailpit): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "Could not start Mailpit in a Docker container "
            "(Error while fetching server API version). Is Docker running?"
        ]
    )
    assert "During handling of the above exception" not in result.stdout.str()


def test_the_container_fixture_needs_the_setting(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_container(mailpit_container): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*needs mailpit_container = true, or --mailpit-container.*"])


# mailpit_smtp without a container


@pytest.mark.parametrize(
    ("ini", "env", "expected"),
    [
        ("", None, ("localhost", 1025)),
        ("mailpit_smtp = mail.test:2525", None, ("mail.test", 2525)),
        ("mailpit_smtp = mail.test:2525", "smtp.test:25", ("smtp.test", 25)),
        ("", "[::1]:1025", ("::1", 1025)),
    ],
)
def test_mailpit_smtp_settings(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    ini: str,
    env: str | None,
    expected: tuple[str, int],
) -> None:
    if env is not None:
        monkeypatch.setenv("MAILPIT_SMTP", env)
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile(f"def test_smtp(mailpit_smtp): assert mailpit_smtp == {expected!r}")

    pytester.runpytest().assert_outcomes(passed=1)


@pytest.mark.parametrize("value", ["mail.test", "mail.test:smtp", ":1025", "mail.test:99999"])
def test_invalid_smtp_settings_stop_the_run(pytester: pytest.Pytester, value: str) -> None:
    pytester.makeini(f"[pytest]\nmailpit_smtp = {value}\n")
    pytester.makepyfile("def test_nothing(): pass")

    result = pytester.runpytest()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*The Mailpit SMTP server must be host:port*"])


def test_smtp_server_reads_well() -> None:
    server: Any = SMTPServer("mail.test", 2525)

    assert str(server) == "mail.test:2525"
    assert server.host == "mail.test"
    _, port = server
    assert port == 2525
