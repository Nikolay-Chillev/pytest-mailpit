"""Typed, read-only models of Mailpit's API responses.

Field names are snake_case versions of Mailpit's JSON keys. Fields that newer
Mailpit versions added have defaults and unknown fields are ignored, so the
models parse responses from every supported server version.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from pytest_mailpit.errors import MailpitAssertionError
from pytest_mailpit.extract import Link, filter_links, find_codes, find_links, html_to_text

# Longest excerpt of a message body shown in a failure.
_EXCERPT_CHARS = 300


@dataclass(frozen=True, slots=True)
class Address:
    address: str
    name: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> Self:
        data = data or {}
        return cls(address=data.get("Address") or "", name=data.get("Name") or "")

    def __str__(self) -> str:
        return f"{self.name} <{self.address}>" if self.name else self.address


@dataclass(frozen=True, slots=True)
class Attachment:
    part_id: str
    file_name: str
    content_type: str
    size: int
    content_id: str = ""
    # Checksum name ("MD5", "SHA1", "SHA256") to hex digest.
    checksums: Mapping[str, str] = field(default_factory=dict, hash=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            part_id=data.get("PartID") or "",
            file_name=data.get("FileName") or "",
            content_type=data.get("ContentType") or "",
            size=data.get("Size") or 0,
            content_id=data.get("ContentID") or "",
            checksums=dict(data.get("Checksums") or {}),
        )


@dataclass(frozen=True, slots=True)
class ListUnsubscribe:
    """The List-Unsubscribe header as Mailpit parsed it."""

    header: str = ""
    header_post: str = ""
    # At most one mailto: and one HTTP(S) link.
    links: tuple[str, ...] = ()
    # Validation errors Mailpit found in the header, if any.
    errors: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> Self:
        data = data or {}
        return cls(
            header=data.get("Header") or "",
            header_post=data.get("HeaderPost") or "",
            links=tuple(data.get("Links") or ()),
            errors=data.get("Errors") or "",
        )


@dataclass(frozen=True, slots=True)
class MessageSummary:
    """An entry of a message list or search result."""

    id: str
    message_id: str
    sender: Address  # the From header
    to: tuple[Address, ...]
    cc: tuple[Address, ...]
    bcc: tuple[Address, ...]
    reply_to: tuple[Address, ...]
    subject: str
    # When Mailpit received the message.
    created: datetime
    tags: tuple[str, ...]
    size: int
    # The number of attachments.
    attachments: int
    # Up to 250 characters of the text.
    snippet: str
    read: bool
    # The SMTP or Send API username, if the sender authenticated (Mailpit 1.26.2+).
    username: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            id=data["ID"],
            message_id=data.get("MessageID") or "",
            sender=Address.from_api(data.get("From")),
            to=_addresses(data.get("To")),
            cc=_addresses(data.get("Cc")),
            bcc=_addresses(data.get("Bcc")),
            reply_to=_addresses(data.get("ReplyTo")),
            subject=data.get("Subject") or "",
            created=datetime.fromisoformat(data["Created"]),
            tags=tuple(data.get("Tags") or ()),
            size=data.get("Size") or 0,
            attachments=data.get("Attachments") or 0,
            snippet=data.get("Snippet") or "",
            read=bool(data.get("Read")),
            username=data.get("Username") or "",
        )


@dataclass(frozen=True, slots=True)
class Message:
    """A whole message, as returned by ``GET /api/v1/message/{ID}``."""

    id: str
    message_id: str
    sender: Address  # the From header
    to: tuple[Address, ...]
    cc: tuple[Address, ...]
    bcc: tuple[Address, ...]
    reply_to: tuple[Address, ...]
    return_path: str
    subject: str
    # The Date header, or when Mailpit received the message if the header is missing.
    date: datetime
    tags: tuple[str, ...]
    text: str
    html: str
    size: int
    attachments: tuple[Attachment, ...]
    # Inline parts such as embedded images.
    inline: tuple[Attachment, ...]
    list_unsubscribe: ListUnsubscribe
    username: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            id=data["ID"],
            message_id=data.get("MessageID") or "",
            sender=Address.from_api(data.get("From")),
            to=_addresses(data.get("To")),
            cc=_addresses(data.get("Cc")),
            bcc=_addresses(data.get("Bcc")),
            reply_to=_addresses(data.get("ReplyTo")),
            return_path=data.get("ReturnPath") or "",
            subject=data.get("Subject") or "",
            date=datetime.fromisoformat(data["Date"]),
            tags=tuple(data.get("Tags") or ()),
            text=data.get("Text") or "",
            html=data.get("HTML") or "",
            size=data.get("Size") or 0,
            attachments=tuple(Attachment.from_api(item) for item in data.get("Attachments") or ()),
            inline=tuple(Attachment.from_api(item) for item in data.get("Inline") or ()),
            list_unsubscribe=ListUnsubscribe.from_api(data.get("ListUnsubscribe")),
            username=data.get("Username") or "",
        )

    def links(
        self,
        contains: str | None = None,
        *,
        pattern: str | re.Pattern[str] | None = None,
        text: str | None = None,
    ) -> list[str]:
        """The http(s) links in the message, from the HTML and the text part.

        ``contains`` keeps the URLs that contain it, ``pattern`` those matching
        a regular expression, and ``text`` the HTML links whose visible text
        contains it (case-insensitive).
        """
        found = filter_links(self._links(), contains=contains, pattern=pattern, text=text)
        return [link.url for link in found]

    def link(
        self,
        contains: str | None = None,
        *,
        pattern: str | re.Pattern[str] | None = None,
        text: str | None = None,
    ) -> str:
        """The one link matching the filters of :meth:`links`.

        Raises MailpitAssertionError, a test failure, unless exactly one matches.
        """
        every_link = self._links()
        found = filter_links(every_link, contains=contains, pattern=pattern, text=text)
        if len(found) == 1:
            return found[0].url
        filters = _describe_filters(contains=contains, pattern=pattern, text=text)
        lines = [f"Expected one link{filters} in {self._describe()}, found {len(found)}."]
        if every_link:
            lines.append("Links in the message:")
            lines += [f"  {_describe_link(link)}" for link in every_link]
        else:
            lines.append("The message has no http(s) links.")
        raise MailpitAssertionError("\n".join(lines))

    def codes(self, pattern: str | re.Pattern[str] | None = None) -> list[str]:
        """One-time codes in the message, the most likely first.

        Without ``pattern``, a code is a run of 4-8 digits near words such as
        "code", "OTP", "verification" or "код". With ``pattern``, every match of
        the regular expression (its first group, if it has one).
        """
        return find_codes(self.text, self.html, pattern=pattern)

    def code(self, pattern: str | re.Pattern[str] | None = None) -> str:
        """The one code :meth:`codes` finds.

        Raises MailpitAssertionError, a test failure, unless exactly one is found.
        """
        found = self.codes(pattern)
        if len(found) == 1:
            return found[0]
        what = f"code matching {pattern!r}" if pattern is not None else "one-time code"
        lines = [f"Expected one {what} in {self._describe()}, found {len(found)}"]
        if found:
            lines[0] += f": {', '.join(found)}."
            if pattern is None:
                lines.append("Pass pattern= to say which one is the code.")
        else:
            lines[0] += "."
            body = " ".join((self.text if self.text.strip() else html_to_text(self.html)).split())
            if len(body) > _EXCERPT_CHARS:
                body = body[:_EXCERPT_CHARS] + "..."
            lines.append(f"Text of the message: {body!r}")
        raise MailpitAssertionError("\n".join(lines))

    def _links(self) -> list[Link]:
        return find_links(self.text, self.html)

    def _describe(self) -> str:
        recipients = ", ".join(address.address for address in self.to) or "no one"
        return f"message {self.subject!r} to {recipients}"


def _describe_filters(
    *, contains: str | None, pattern: str | re.Pattern[str] | None, text: str | None
) -> str:
    parts = []
    if contains is not None:
        parts.append(f"containing {contains!r}")
    if pattern is not None:
        shown = pattern.pattern if isinstance(pattern, re.Pattern) else pattern
        parts.append(f"matching {shown!r}")
    if text is not None:
        parts.append(f"with text {text!r}")
    return f" {' and '.join(parts)}" if parts else ""


def _describe_link(link: Link) -> str:
    return f"{link.url}  (text: {link.text!r})" if link.text else link.url


@dataclass(frozen=True, slots=True)
class MessageList:
    """One page of a message list or search result, newest message first."""

    messages: tuple[MessageSummary, ...]
    # Messages matching the search (all messages for a plain list).
    messages_count: int
    messages_unread: int
    # Messages in the whole mailbox.
    total: int
    unread: int
    # The offset of this page.
    start: int
    # All tags in the mailbox.
    tags: tuple[str, ...]

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            messages=tuple(MessageSummary.from_api(item) for item in data.get("messages") or ()),
            messages_count=data.get("messages_count") or 0,
            messages_unread=data.get("messages_unread") or 0,
            total=data.get("total") or 0,
            unread=data.get("unread") or 0,
            start=data.get("start") or 0,
            tags=tuple(data.get("tags") or ()),
        )


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """``GET /api/v1/info``: the server version and mailbox totals."""

    version: str
    latest_version: str
    database: str
    database_size: int
    messages: int
    unread: int
    # Tag to the number of messages with it.
    tags: Mapping[str, int] = field(default_factory=dict, hash=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            version=data.get("Version") or "",
            latest_version=data.get("LatestVersion") or "",
            database=data.get("Database") or "",
            database_size=data.get("DatabaseSize") or 0,
            messages=data.get("Messages") or 0,
            unread=data.get("Unread") or 0,
            tags=dict(data.get("Tags") or {}),
        )


def _addresses(data: Any) -> tuple[Address, ...]:
    return tuple(Address.from_api(item) for item in data or ())
