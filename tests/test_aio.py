"""AsyncMailpitClient, AsyncInbox and their fixtures, run with asyncio.run."""

import asyncio
import json
import re
import threading
import time
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from requests import PreparedRequest

from pytest_mailpit import (
    AsyncInbox,
    AsyncMailpitClient,
    Attachment,
    ChaosTriggers,
    Inbox,
    MailpitAssertionError,
    MailpitClient,
)
from tests import samples
from tests.test_waiting import page, summary

URL = "http://localhost:8025/"
SEARCH = re.compile(re.escape(f"{URL}api/v1/search") + r"\?.*")
MESSAGE = re.compile(re.escape(f"{URL}api/v1/message/") + r"[^/]+$")
ADDRESS = "new@example.com"


class Recorder:
    """Stands in for MailpitClient: records each call, and whether it ran in a worker thread."""

    url = URL

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any], bool]] = []

    def __getattr__(self, name: str) -> Any:
        def method(*args: Any, **kwargs: Any) -> str:
            in_worker = threading.current_thread() is not threading.main_thread()
            self.calls.append((name, args, kwargs, in_worker))
            return f"{name} result"

        return method


ATTACHMENT = Attachment(
    part_id="2", file_name="a.pdf", content_type="application/pdf", size=1, message_id="m1"
)


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "called"),
    [
        ("info", (), {}, ("info", (), {})),
        ("is_ready", (), {}, ("is_ready", (), {})),
        ("server_time", (), {}, ("server_time", (), {})),
        ("messages", (), {"start": 50}, ("messages", (), {"start": 50, "limit": 50})),
        ("search", ("tag:x",), {"limit": 5}, ("search", ("tag:x",), {"start": 0, "limit": 5})),
        ("search_all", ("tag:x",), {}, ("search_all", ("tag:x",), {"page_size": 250})),
        ("get_message", (), {}, ("get_message", ("latest",), {})),
        ("get_headers", ("m1",), {}, ("get_headers", ("m1",), {})),
        ("get_raw", ("m1",), {}, ("get_raw", ("m1",), {})),
        ("get_part", ("m1", "2"), {}, ("get_part", ("m1", "2"), {})),
        (
            "check_links",
            ("m1",),
            {"follow_redirects": True},
            ("check_links", ("m1",), {"follow_redirects": True}),
        ),
        ("check_html", ("m1",), {}, ("check_html", ("m1",), {})),
        ("get_attachment", (ATTACHMENT,), {}, ("get_attachment", (ATTACHMENT,), {})),
        ("delete_messages", (iter(["a", "b"]),), {}, ("delete_messages", (["a", "b"],), {})),
        ("delete_search", ("tag:x",), {}, ("delete_search", ("tag:x",), {})),
        ("delete_all", (), {}, ("delete_all", (), {})),
        ("mark_read", (("a",),), {"read": False}, ("mark_read", (["a"],), {"read": False})),
        ("set_tags", (iter(["a"]), ("x",)), {}, ("set_tags", (["a"], ["x"]), {})),
        ("chaos", (), {}, ("chaos", (), {})),
        ("set_chaos", (ChaosTriggers(),), {}, ("set_chaos", (ChaosTriggers(),), {})),
    ],
)
def test_every_request_runs_in_a_worker_thread(
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    called: tuple[str, tuple[Any, ...], dict[str, Any]],
) -> None:
    recorder = Recorder()
    client = AsyncMailpitClient(cast(MailpitClient, recorder))

    result = asyncio.run(getattr(client, method)(*args, **kwargs))

    returns_nothing = method in {
        "delete_messages",
        "delete_search",
        "delete_all",
        "mark_read",
        "set_tags",
    }
    assert result == (None if returns_nothing else f"{called[0]} result")
    assert recorder.calls == [(*called, True)]


def test_the_client_from_a_url() -> None:
    client = AsyncMailpitClient("http://user:secret@mailpit.test:8025/")

    assert client.url == "http://mailpit.test:8025/"
    assert repr(client) == "AsyncMailpitClient('http://mailpit.test:8025/')"
    assert client.view_url("m1") == "http://mailpit.test:8025/view/m1"
    assert client.html_url("m1") == "http://mailpit.test:8025/view/m1.html"
    assert client.search_url("tag:x") == "http://mailpit.test:8025/search?q=tag%3Ax"
    assert AsyncMailpitClient().url == URL


def test_async_with_closes_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMailpitClient(URL)
    closed: list[bool] = []
    monkeypatch.setattr(client.sync, "close", lambda: closed.append(True))

    async def use() -> None:
        async with client as entered:
            assert entered is client

    asyncio.run(use())

    assert closed == [True]


# Waiting


@pytest.fixture
def arrives_on_the_third_poll() -> Iterator[responses.RequestsMock]:
    polls = iter([page(), page(), page(summary("m1", to=ADDRESS))])

    def search(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        return 200, {}, json.dumps(next(polls, page(summary("m1", to=ADDRESS))))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, SEARCH, callback=search)
        mock.get(MESSAGE, json=samples.MESSAGE | {"ID": "m1"})
        mock.get(f"{URL}api/v1/messages", json=page())
        yield mock


def test_waiting_lets_the_event_loop_run(arrives_on_the_third_poll: responses.RequestsMock) -> None:
    client = AsyncMailpitClient(MailpitClient(URL, poll_interval=0.05))
    ticks = 0

    async def application() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    async def test() -> str:
        running = asyncio.create_task(application())
        message = await client.wait_for_message(recipient=ADDRESS)
        running.cancel()
        return message.id

    assert asyncio.run(test()) == "m1"
    assert ticks >= 5  # the loop ran during the two pauses between polls


def test_a_timeout_fails_as_the_sync_client_does(
    arrives_on_the_third_poll: responses.RequestsMock,
) -> None:
    sync = MailpitClient(URL)
    with pytest.raises(MailpitAssertionError) as expected:
        sync.wait_for_message(recipient="nobody@example.com", timeout=0)

    with pytest.raises(MailpitAssertionError) as failure:
        asyncio.run(
            AsyncMailpitClient(sync).wait_for_message(recipient="nobody@example.com", timeout=0)
        )

    assert str(failure.value) == str(expected.value)
    # Raised in the event loop, so the traceback has no worker thread in it.
    assert not any("concurrent" in str(entry.path) for entry in failure.traceback)


def test_too_many_messages_fail() -> None:
    found = page(summary("m1", to=ADDRESS), summary("m2", to=ADDRESS))
    with responses.RequestsMock() as mock:
        mock.get(SEARCH, json=found)
        with pytest.raises(MailpitAssertionError, match=r"Expected 1 message matching .*, found 2"):
            asyncio.run(AsyncMailpitClient(URL).wait_for_messages(1, recipient=ADDRESS))


def test_assert_no_message() -> None:
    client = AsyncMailpitClient(MailpitClient(URL, poll_interval=0.05))
    with responses.RequestsMock() as mock:
        mock.get(SEARCH, json=page())
        started = time.monotonic()
        asyncio.run(client.assert_no_message(recipient=ADDRESS, within=0.1))
        assert time.monotonic() - started >= 0.1

        mock.replace(responses.GET, SEARCH, json=page(summary("m1", to=ADDRESS)))
        with pytest.raises(MailpitAssertionError, match="Expected no message matching"):
            asyncio.run(client.assert_no_message(recipient=ADDRESS))


def test_invalid_waits_fail_at_once() -> None:
    client = AsyncMailpitClient(URL)

    with pytest.raises(ValueError, match="count must be at least 1"):
        asyncio.run(client.wait_for_messages(0, recipient=ADDRESS))
    with pytest.raises(ValueError, match="Give a query"):
        asyncio.run(client.assert_no_message())


# AsyncInbox


def test_the_async_inbox_waits_for_its_address(
    arrives_on_the_third_poll: responses.RequestsMock,
) -> None:
    inbox = AsyncInbox(Inbox(MailpitClient(URL, poll_interval=0.01), ADDRESS, wait_timeout=5))

    message = asyncio.run(inbox.wait_for_message(subject="Hello"))
    [again] = asyncio.run(inbox.wait_for_messages(1, sender="orders@shop.example.test", query="x"))

    assert message.id == again.id == "m1"
    queries = [
        parse_qs(urlsplit(call.request.url or "").query)["query"][0]
        for call in arrives_on_the_third_poll.calls
        if "/search" in (call.request.url or "")
    ]
    assert f'addressed:"{ADDRESS}"' in queries[0]
    assert 'subject:"Hello"' in queries[0]


def test_the_async_inbox_uses_its_timeout(
    arrives_on_the_third_poll: responses.RequestsMock,
) -> None:
    inbox = AsyncInbox(Inbox(MailpitClient(URL), "nobody@example.com", wait_timeout=0))

    with pytest.raises(MailpitAssertionError, match="within 0s"):
        asyncio.run(inbox.wait_for_message())
    asyncio.run(inbox.assert_no_message(within=0))


def test_the_async_inbox_lists_and_clears_its_messages() -> None:
    inbox = AsyncInbox(Inbox(MailpitClient(URL), ADDRESS, wait_timeout=5))
    with responses.RequestsMock() as mock:
        mock.get(SEARCH, json=page(summary("m1", to=ADDRESS), summary("m2", to="other@x.test")))
        mock.delete(f"{URL}api/v1/messages", body="ok")

        assert [found.id for found in asyncio.run(inbox.messages())] == ["m1"]
        asyncio.run(inbox.clear())

        assert json.loads(mock.calls[-1].request.body or "{}") == {"IDs": ["m1"]}
    assert str(inbox) == inbox.address == ADDRESS
    assert repr(inbox) == f"AsyncInbox({ADDRESS!r})"


# The fixtures, in inner sessions


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit at the default URL, holding one message for every inbox."""
    for name in ("MAILPIT_URL", "PYTEST_XDIST_WORKER"):
        monkeypatch.delenv(name, raising=False)

    def one_per_address(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        query = parse_qs(urlsplit(request.url or "").query)["query"][0]
        address = re.search(r'addressed:"([^"]+)"', query)
        found = [summary("m1", to=address.group(1))] if address else []
        return 200, {}, json.dumps(page(*found))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, SEARCH, callback=one_per_address)
        mock.get(MESSAGE, json=samples.MESSAGE | {"ID": "m1"})
        mock.get(f"{URL}api/v1/messages", json=page())
        mock.delete(f"{URL}api/v1/messages", body="ok")
        yield mock


def test_the_async_fixtures(pytester: pytest.Pytester, server: responses.RequestsMock) -> None:
    pytester.makepyfile(
        """
        import asyncio

        from pytest_mailpit import AsyncInbox, AsyncMailpitClient


        def test_waits(mailpit, mailpit_async, mailpit_inbox, mailpit_async_inbox):
            assert isinstance(mailpit_async, AsyncMailpitClient)
            assert mailpit_async.sync is mailpit
            assert isinstance(mailpit_async_inbox, AsyncInbox)
            assert mailpit_async_inbox.sync is mailpit_inbox

            message = asyncio.run(mailpit_async_inbox.wait_for_message())

            assert message.id == "m1"


        def test_fails(mailpit_async_inbox):
            asyncio.run(mailpit_async_inbox.wait_for_messages(2, timeout=0))
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, failed=1)
    # The async inbox is mailpit_inbox: a failure lists its messages, and keeps them.
    result.stdout.fnmatch_lines(["*Mailpit messages to pytest-*@example.com*"])
    deleted = [call for call in server.calls if call.request.method == "DELETE"]
    assert len(deleted) == 1
