"""The client and the inbox for async tests: the same methods, to await.

Waiting yields to the event loop between polls, so an application under test
that sends email from the same loop keeps running. Each request to Mailpit
runs in a worker thread through the sync client, so pytest-mailpit needs no
async HTTP library.
"""

import asyncio
from collections.abc import Iterable
from datetime import datetime
from types import TracebackType
from typing import Self

from pytest_mailpit._args import strings
from pytest_mailpit.client import DEFAULT_URL, MailpitClient, _Failed, _Wait
from pytest_mailpit.errors import MailpitAssertionError
from pytest_mailpit.inbox import Inbox
from pytest_mailpit.models import (
    Attachment,
    ChaosTriggers,
    HTMLCheck,
    LinkCheck,
    Message,
    MessageList,
    MessageSummary,
    ServerInfo,
)


class AsyncMailpitClient:
    """MailpitClient for async tests: every method that asks Mailpit is awaited.

    ``client`` is the MailpitClient to use, or the URL of Mailpit; for
    credentials, TLS and timeouts, pass a MailpitClient. ``sync`` is that
    client, for anything that needs no awaiting.
    """

    def __init__(self, client: MailpitClient | str = DEFAULT_URL) -> None:
        self.sync = MailpitClient(client) if isinstance(client, str) else client

    @property
    def url(self) -> str:
        """Mailpit's URL, without credentials."""
        return self.sync.url

    def __repr__(self) -> str:
        return f"AsyncMailpitClient({self.url!r})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the MailpitClient, ``sync``."""
        self.sync.close()

    # Server

    async def info(self) -> ServerInfo:
        return await asyncio.to_thread(self.sync.info)

    async def is_ready(self) -> bool:
        return await asyncio.to_thread(self.sync.is_ready)

    async def server_time(self) -> datetime:
        return await asyncio.to_thread(self.sync.server_time)

    # Reading

    async def messages(self, *, start: int = 0, limit: int = 50) -> MessageList:
        return await asyncio.to_thread(self.sync.messages, start=start, limit=limit)

    async def search(self, query: str, *, start: int = 0, limit: int = 50) -> MessageList:
        return await asyncio.to_thread(self.sync.search, query, start=start, limit=limit)

    async def search_all(self, query: str, *, page_size: int = 250) -> list[MessageSummary]:
        return await asyncio.to_thread(self.sync.search_all, query, page_size=page_size)

    async def get_message(self, message_id: str = "latest") -> Message:
        return await asyncio.to_thread(self.sync.get_message, message_id)

    async def get_headers(self, message_id: str) -> dict[str, list[str]]:
        return await asyncio.to_thread(self.sync.get_headers, message_id)

    async def get_raw(self, message_id: str) -> bytes:
        return await asyncio.to_thread(self.sync.get_raw, message_id)

    async def get_part(self, message_id: str, part_id: str) -> bytes:
        return await asyncio.to_thread(self.sync.get_part, message_id, part_id)

    async def check_links(self, message_id: str, *, follow_redirects: bool = False) -> LinkCheck:
        return await asyncio.to_thread(
            self.sync.check_links, message_id, follow_redirects=follow_redirects
        )

    async def check_html(self, message_id: str) -> HTMLCheck:
        return await asyncio.to_thread(self.sync.check_html, message_id)

    async def get_attachment(self, attachment: Attachment) -> bytes:
        return await asyncio.to_thread(self.sync.get_attachment, attachment)

    def view_url(self, message_id: str) -> str:
        return self.sync.view_url(message_id)

    def html_url(self, message_id: str) -> str:
        return self.sync.html_url(message_id)

    def search_url(self, query: str) -> str:
        return self.sync.search_url(query)

    # Waiting: the criteria and failures of MailpitClient's methods.

    async def wait_for_message(
        self,
        query: str | None = None,
        *,
        recipient: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        tag: str | None = None,
        since: datetime | None = None,
        timeout: float | None = None,
    ) -> Message:
        """Wait until exactly one matching message has arrived, and return it."""
        __tracebackhide__ = True
        [message] = await self.wait_for_messages(
            1,
            query,
            recipient=recipient,
            sender=sender,
            subject=subject,
            tag=tag,
            since=since,
            timeout=timeout,
        )
        return message

    async def wait_for_messages(
        self,
        count: int,
        query: str | None = None,
        *,
        recipient: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        tag: str | None = None,
        since: datetime | None = None,
        timeout: float | None = None,
    ) -> list[Message]:
        """Wait until exactly ``count`` matching messages have arrived; oldest first."""
        __tracebackhide__ = True
        wait = self.sync._wait_for(count, query, recipient, sender, subject, tag, since, timeout)
        return await _finish(wait)

    async def assert_no_message(
        self,
        query: str | None = None,
        *,
        recipient: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        tag: str | None = None,
        since: datetime | None = None,
        within: float = 2.0,
    ) -> None:
        """Fail the test if a matching message arrives within ``within`` seconds."""
        __tracebackhide__ = True
        wait = self.sync._wait_for_none(query, recipient, sender, subject, tag, since, within)
        await _finish(wait)

    # Changing

    async def delete_messages(self, message_ids: Iterable[str]) -> None:
        await asyncio.to_thread(self.sync.delete_messages, strings(message_ids, "message IDs"))

    async def delete_search(self, query: str) -> None:
        await asyncio.to_thread(self.sync.delete_search, query)

    async def delete_all(self) -> None:
        await asyncio.to_thread(self.sync.delete_all)

    async def mark_read(self, message_ids: Iterable[str], *, read: bool = True) -> None:
        await asyncio.to_thread(self.sync.mark_read, strings(message_ids, "message IDs"), read=read)

    async def set_tags(self, message_ids: Iterable[str], tags: Iterable[str]) -> None:
        await asyncio.to_thread(
            self.sync.set_tags, strings(message_ids, "message IDs"), strings(tags, "tags")
        )

    # Chaos

    async def chaos(self) -> ChaosTriggers:
        return await asyncio.to_thread(self.sync.chaos)

    async def set_chaos(self, triggers: ChaosTriggers) -> ChaosTriggers:
        return await asyncio.to_thread(self.sync.set_chaos, triggers)


class AsyncInbox:
    """An Inbox for async tests: the same address, with methods to await.

    ``sync`` is the Inbox, for its address and anything that needs no awaiting.
    """

    def __init__(self, inbox: Inbox) -> None:
        self.sync = inbox
        self.client = AsyncMailpitClient(inbox.client)

    @property
    def address(self) -> str:
        return self.sync.address

    def __str__(self) -> str:
        return self.address

    def __repr__(self) -> str:
        return f"AsyncInbox({self.address!r})"

    async def wait_for_message(
        self,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        timeout: float | None = None,
    ) -> Message:
        """Wait until exactly one matching message has arrived, and return it."""
        __tracebackhide__ = True
        return await self.client.wait_for_message(
            query,
            recipient=self.address,
            sender=sender,
            subject=subject,
            timeout=self.sync.wait_timeout if timeout is None else timeout,
        )

    async def wait_for_messages(
        self,
        count: int,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        timeout: float | None = None,
    ) -> list[Message]:
        """Wait until exactly ``count`` matching messages have arrived; oldest first."""
        __tracebackhide__ = True
        return await self.client.wait_for_messages(
            count,
            query,
            recipient=self.address,
            sender=sender,
            subject=subject,
            timeout=self.sync.wait_timeout if timeout is None else timeout,
        )

    async def assert_no_message(
        self,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        within: float = 2.0,
    ) -> None:
        """Fail the test if a matching message arrives within ``within`` seconds."""
        __tracebackhide__ = True
        await self.client.assert_no_message(
            query, recipient=self.address, sender=sender, subject=subject, within=within
        )

    async def messages(self) -> list[MessageSummary]:
        """The messages sent to the address so far, oldest first."""
        return await asyncio.to_thread(self.sync.messages)

    async def clear(self) -> None:
        """Delete the messages sent to the address, and no others."""
        await asyncio.to_thread(self.sync.clear)


async def _finish(wait: _Wait) -> list[Message]:
    """Poll until the wait is over, awaiting between polls."""
    __tracebackhide__ = True
    while (result := await asyncio.to_thread(wait.poll)) is None:
        await asyncio.sleep(wait.pause())
    # Raised here, not in the worker thread, so the failure points at the test.
    if isinstance(result, _Failed):
        raise MailpitAssertionError(result.message)
    return result
