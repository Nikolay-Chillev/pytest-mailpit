"""A client for Mailpit's REST API (``/api/v1``)."""

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Self
from urllib.parse import urljoin

from pytest_mailpit._http import Transport
from pytest_mailpit._report import message_table
from pytest_mailpit.errors import MailpitAssertionError, MailpitError
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
from pytest_mailpit.search import build_query

DEFAULT_URL = "http://localhost:8025/"
# How many of the newest messages a failure lists.
_FAILURE_TABLE_SIZE = 10


class MailpitClient:
    """Reads, waits for and deletes the messages caught by a Mailpit server.

    ``url`` is the address of Mailpit's web UI, including the web root if
    Mailpit runs with ``--webroot``. ``username`` and ``password`` are for
    Mailpit's UI authentication (``--ui-auth``). ``verify`` is passed to
    requests: ``False`` skips TLS verification, a path selects a CA bundle.
    ``timeout`` limits each HTTP request; ``wait_timeout`` and
    ``poll_interval`` are the defaults of the ``wait_for_*`` methods.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        username: str | None = None,
        password: str | None = None,
        verify: bool | str = True,
        timeout: float = 10.0,
        wait_timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> None:
        _require_positive(poll_interval=poll_interval)
        _require_not_negative(wait_timeout=wait_timeout)
        self._http = Transport(
            url, username=username, password=password, verify=verify, timeout=timeout
        )
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval

    @property
    def url(self) -> str:
        """Mailpit's URL, without any credentials it contained."""
        return self._http.display_url

    def __repr__(self) -> str:
        return f"MailpitClient({self.url!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # Server

    def info(self) -> ServerInfo:
        return ServerInfo.from_api(self._http.get_json("api/v1/info"))

    def is_ready(self) -> bool:
        """Whether Mailpit answers its readiness probe. Never raises."""
        try:
            self._http.request("GET", "readyz")
        except MailpitError:
            return False
        return True

    def server_time(self) -> datetime:
        """The current time on the Mailpit server, to the second, in UTC.

        Use it as ``since`` of the ``wait_for_*`` methods when the server's clock
        may differ from the clock of the machine running the tests.
        """
        response = self._http.request("GET", "livez")
        try:
            server_time = parsedate_to_datetime(response.headers["Date"])
        except (KeyError, TypeError, ValueError):
            # No usable Date header: fall back to the local clock.
            return datetime.now(UTC)
        if server_time.tzinfo is None:  # "-0000" means UTC without saying so
            server_time = server_time.replace(tzinfo=UTC)
        return server_time.astimezone(UTC)

    # Reading

    def messages(self, *, start: int = 0, limit: int = 50) -> MessageList:
        """One page of all messages, newest first."""
        return MessageList.from_api(
            self._http.get_json("api/v1/messages", params={"start": start, "limit": limit})
        )

    def search(self, query: str, *, start: int = 0, limit: int = 50) -> MessageList:
        """One page of the messages matching ``query``, newest first.

        ``query`` uses Mailpit's search syntax; :func:`pytest_mailpit.search.build_query`
        builds one with correct quoting.
        """
        _require_query(query)
        return MessageList.from_api(
            self._http.get_json(
                "api/v1/search", params={"query": query, "start": start, "limit": limit}
            )
        )

    def search_all(self, query: str, *, page_size: int = 250) -> list[MessageSummary]:
        """All messages matching ``query``, newest first, fetched page by page."""
        found: dict[str, MessageSummary] = {}
        start = 0
        while True:
            page = self.search(query, start=start, limit=page_size)
            # Messages that arrive meanwhile shift the pages, so an entry can appear twice.
            for summary in page.messages:
                found.setdefault(summary.id, summary)
            start += len(page.messages)
            if not page.messages or start >= page.messages_count:
                return list(found.values())

    def get_message(self, message_id: str = "latest") -> Message:
        """The whole message; ``"latest"`` is the newest one.

        Mailpit marks a message as read when it is fetched this way.
        """
        data = self._http.get_json(f"api/v1/message/{message_id}")
        return Message.from_api(data, client=self)

    def get_headers(self, message_id: str) -> dict[str, list[str]]:
        """All headers of a message; a header can occur more than once."""
        headers: dict[str, list[str]] = self._http.get_json(f"api/v1/message/{message_id}/headers")
        return headers

    def get_raw(self, message_id: str) -> bytes:
        """The message source, as an .eml file would hold it."""
        return self._http.request("GET", f"api/v1/message/{message_id}/raw").content

    def get_part(self, message_id: str, part_id: str) -> bytes:
        """The content of an attachment or inline part, by its ``part_id``."""
        return self._http.request("GET", f"api/v1/message/{message_id}/part/{part_id}").content

    def check_links(self, message_id: str, *, follow_redirects: bool = False) -> LinkCheck:
        """Mailpit's link check: a HEAD request to every link in the message."""
        params = {"follow": "true"} if follow_redirects else None
        return LinkCheck.from_api(
            self._http.get_json(f"api/v1/message/{message_id}/link-check", params=params)
        )

    def check_html(self, message_id: str) -> HTMLCheck:
        """Mailpit's HTML check: how well email clients support the message's HTML and CSS."""
        return HTMLCheck.from_api(self._http.get_json(f"api/v1/message/{message_id}/html-check"))

    def get_attachment(self, attachment: Attachment) -> bytes:
        """The content of an attachment or inline part of a message this client fetched."""
        if not attachment.message_id:
            raise ValueError(
                "The attachment does not say which message it belongs to; "
                "use get_part(message_id, part_id)"
            )
        return self.get_part(attachment.message_id, attachment.part_id)

    def view_url(self, message_id: str) -> str:
        """The page of the message in Mailpit's web UI, without credentials."""
        return urljoin(self.url, f"view/{message_id}")

    def html_url(self, message_id: str) -> str:
        """Just the message's HTML part, with inline images, as Mailpit renders it for
        UI tests; without credentials."""
        return urljoin(self.url, f"view/{message_id}.html")

    # Waiting
    #
    # Every method takes a Mailpit search ``query``, criteria, or both:
    # ``recipient`` and ``sender`` match a whole address, case-insensitively
    # (``recipient`` in To, Cc or Bcc); ``subject`` and ``tag`` match any part,
    # as Mailpit's search does; ``since`` (timezone-aware) skips messages that
    # arrived earlier. Connection and API errors are raised as they happen,
    # never mistaken for a missing message.

    def wait_for_message(
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
        """Wait until exactly one matching message has arrived, and return it.

        Raises MailpitAssertionError, a test failure, if none arrives within
        ``timeout`` seconds or if more than one matches. The failure lists the
        newest messages in Mailpit, to show what arrived instead.
        """
        # Hide this frame from pytest tracebacks: failures point at the calling test.
        __tracebackhide__ = True
        [message] = self.wait_for_messages(
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

    def wait_for_messages(
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
        """Wait until exactly ``count`` matching messages have arrived, and
        return them, oldest first.

        Raises MailpitAssertionError, a test failure, if fewer arrive within
        ``timeout`` seconds or if more than ``count`` match.
        """
        __tracebackhide__ = True
        if count < 1:
            raise ValueError("count must be at least 1; use assert_no_message to expect none")
        criteria = _Criteria.build(query, recipient, sender, subject, tag, since)
        timeout = self.wait_timeout if timeout is None else timeout
        _require_not_negative(timeout=timeout)
        expected = f"{count} message{'s' if count > 1 else ''} matching {criteria}"
        deadline = time.monotonic() + timeout
        while True:
            found = self._matching(criteria)
            if len(found) > count:
                raise MailpitAssertionError(
                    f"Expected {expected}, found {len(found)}:\n{message_table(found)}"
                )
            if len(found) == count:
                return [self.get_message(summary.id) for summary in found]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                arrived = f"{len(found)} arrived" if found else "none arrived"
                raise MailpitAssertionError(
                    f"Expected {expected} within {timeout:g}s, {arrived}.\n"
                    f"{self._what_arrived(criteria)}"
                )
            time.sleep(min(self.poll_interval, remaining))

    def assert_no_message(
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
        """Check that no matching message arrives during ``within`` seconds.

        Raises MailpitAssertionError, a test failure, as soon as one does.
        """
        __tracebackhide__ = True
        criteria = _Criteria.build(query, recipient, sender, subject, tag, since)
        _require_not_negative(within=within)
        deadline = time.monotonic() + within
        while True:
            found = self._matching(criteria)
            if found:
                raise MailpitAssertionError(
                    f"Expected no message matching {criteria}, found {len(found)}:\n"
                    f"{message_table(found)}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(self.poll_interval, remaining))

    def _matching(self, criteria: "_Criteria") -> list[MessageSummary]:
        found = [
            summary for summary in self.search_all(criteria.query) if criteria.matches(summary)
        ]
        found.reverse()  # oldest first
        return found

    def _what_arrived(self, criteria: "_Criteria") -> str:
        """For a failure: the messages to the recipient, or else the newest in Mailpit.

        Mailpit is often shared by many tests, so the recipient's messages say
        more than the newest ones, which may all belong to other tests.
        """
        try:
            if criteria.recipient is not None:
                query = build_query(addressed=criteria.recipient)
                found = [s for s in self.search_all(query) if criteria.has_recipient(s)]
                if found:
                    return (
                        f"Messages to {criteria.recipient}{_count(found)}:\n"
                        f"{message_table(found[_FAILURE_TABLE_SIZE - 1 :: -1])}"
                    )
            page = self.messages(limit=_FAILURE_TABLE_SIZE)
        except MailpitError as error:
            return f"Could not list the messages in Mailpit: {error}"
        intro = f"No messages to {criteria.recipient}. " if criteria.recipient is not None else ""
        if not page.messages:
            return f"{intro}Mailpit has no messages."
        return (
            f"{intro}Newest messages in Mailpit ({len(page.messages)} of {page.total}):\n"
            f"{message_table(page.messages[::-1])}"
        )

    # Changing

    def delete_messages(self, message_ids: Iterable[str]) -> None:
        """Delete the given messages. An empty list deletes nothing."""
        # Mailpit deletes every message when it gets no IDs, so an empty list must not reach it.
        ids = _unique(message_ids)
        if ids:
            self._http.request("DELETE", "api/v1/messages", json_body={"IDs": ids})

    def delete_search(self, query: str) -> None:
        """Delete the messages matching ``query``."""
        _require_query(query)
        self._http.request("DELETE", "api/v1/search", params={"query": query})

    def delete_all(self) -> None:
        """Delete every message in the mailbox."""
        self._http.request("DELETE", "api/v1/messages")

    def mark_read(self, message_ids: Iterable[str], *, read: bool = True) -> None:
        """Mark the given messages as read, or as unread with ``read=False``."""
        # Without IDs, Mailpit would change every message.
        ids = _unique(message_ids)
        if ids:
            self._http.request("PUT", "api/v1/messages", json_body={"IDs": ids, "Read": read})

    # Chaos: SMTP errors on purpose. Mailpit must run with Chaos enabled
    # (MP_ENABLE_CHAOS=true or --enable-chaos), or it answers with HTTP 400.

    def chaos(self) -> ChaosTriggers:
        """The SMTP errors Mailpit returns on purpose."""
        return ChaosTriggers.from_api(self._http.get_json("api/v1/chaos"))

    def set_chaos(self, triggers: ChaosTriggers) -> ChaosTriggers:
        """Replace all of Mailpit's Chaos triggers and return them as Mailpit applied them.

        They apply to every message Mailpit receives; ``set_chaos(ChaosTriggers())``
        turns every error off.
        """
        response = self._http.request("PUT", "api/v1/chaos", json_body=triggers.to_api())
        return ChaosTriggers.from_api(response.json())


@dataclass(frozen=True, slots=True)
class _Criteria:
    """What a waiting method looks for: a search for Mailpit, refined in the client.

    Mailpit's address filters match substrings ("a@x.test" also finds
    "ba@x.test") and cannot take a time, so exact addresses and ``since`` are
    checked on the results.
    """

    query: str
    recipient: str | None
    sender: str | None
    since: datetime | None

    @classmethod
    def build(
        cls,
        query: str | None,
        recipient: str | None,
        sender: str | None,
        subject: str | None,
        tag: str | None,
        since: datetime | None,
    ) -> Self:
        terms = []
        if query is not None:
            _require_query(query)
            terms.append(query)
        given = {"addressed": recipient, "sender": sender, "subject": subject, "tag": tag}
        criteria = {name: value for name, value in given.items() if value is not None}
        if criteria:
            terms.append(build_query(**criteria))
        if not terms:
            raise ValueError("Give a query, or at least one of recipient, sender, subject and tag")
        if since is not None and since.utcoffset() is None:
            raise ValueError("since must be timezone-aware, e.g. datetime.now(UTC)")
        return cls(
            query=" ".join(terms),
            recipient=recipient.lower() if recipient is not None else None,
            sender=sender.lower() if sender is not None else None,
            since=since,
        )

    def matches(self, summary: MessageSummary) -> bool:
        if not self.has_recipient(summary):
            return False
        if self.sender is not None and summary.sender.address.lower() != self.sender:
            return False
        return self.since is None or summary.created >= self.since

    def has_recipient(self, summary: MessageSummary) -> bool:
        """Whether the message went to the recipient (in To, Cc or Bcc), if one was given."""
        if self.recipient is None:
            return True
        recipients = (*summary.to, *summary.cc, *summary.bcc)
        return any(address.address.lower() == self.recipient for address in recipients)

    def __str__(self) -> str:
        text = self.query
        if self.since is not None:
            text += f" since {self.since.astimezone(UTC):%H:%M:%S} UTC"
        return text


def _count(found: list[MessageSummary]) -> str:
    """ " (3)", or " (12, newest 10 shown)" when the table is cut short."""
    if len(found) > _FAILURE_TABLE_SIZE:
        return f" ({len(found)}, newest {_FAILURE_TABLE_SIZE} shown)"
    return f" ({len(found)})"


def _require_query(query: str) -> None:
    if not query.strip():
        raise ValueError("The search query must not be empty")


def _require_positive(**values: float) -> None:
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value}")


def _require_not_negative(**values: float) -> None:
    for name, value in values.items():
        if value < 0:
            raise ValueError(f"{name} must not be negative, got {value}")


def _unique(message_ids: Iterable[str]) -> list[str]:
    # Duplicate IDs in one delete locked Mailpit's database before v1.30.7.
    if isinstance(message_ids, str):
        raise TypeError("Expected a list of message IDs, got a single string")
    return list(dict.fromkeys(message_ids))
