"""Typed, read-only models of Mailpit's API responses.

Field names are snake_case versions of Mailpit's JSON keys. Fields that newer
Mailpit versions added have defaults and unknown fields are ignored, so the
models parse responses from every supported server version.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self


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
