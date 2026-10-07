"""A client for Mailpit's REST API (``/api/v1``)."""

from collections.abc import Iterable
from types import TracebackType
from typing import Self

from pytest_mailpit._http import Transport
from pytest_mailpit.errors import MailpitError
from pytest_mailpit.models import Message, MessageList, MessageSummary, ServerInfo

DEFAULT_URL = "http://localhost:8025/"


class MailpitClient:
    """Reads and deletes the messages caught by a Mailpit server.

    ``url`` is the address of Mailpit's web UI, including the web root if
    Mailpit runs with ``--webroot``. ``username`` and ``password`` are for
    Mailpit's UI authentication (``--ui-auth``). ``verify`` is passed to
    requests: ``False`` skips TLS verification, a path selects a CA bundle.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        username: str | None = None,
        password: str | None = None,
        verify: bool | str = True,
        timeout: float = 10.0,
    ) -> None:
        self._http = Transport(
            url, username=username, password=password, verify=verify, timeout=timeout
        )

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
        return Message.from_api(self._http.get_json(f"api/v1/message/{message_id}"))

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


def _require_query(query: str) -> None:
    if not query.strip():
        raise ValueError("The search query must not be empty")


def _unique(message_ids: Iterable[str]) -> list[str]:
    # Duplicate IDs in one delete locked Mailpit's database before v1.30.7.
    if isinstance(message_ids, str):
        raise TypeError("Expected a list of message IDs, got a single string")
    return list(dict.fromkeys(message_ids))
