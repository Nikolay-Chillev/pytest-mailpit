"""Typed, read-only models of Mailpit's API responses.

Field names are snake_case versions of Mailpit's JSON keys. Fields that newer
Mailpit versions added have defaults and unknown fields are ignored, so the
models parse responses from every supported server version.
"""

import fnmatch
import inspect
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Self, TypeVar

from pytest_mailpit._args import strings
from pytest_mailpit.errors import MailpitAssertionError
from pytest_mailpit.extract import Link, filter_links, find_codes, find_links, html_to_text

if TYPE_CHECKING:
    from pytest_mailpit.client import MailpitClient

PageT = TypeVar("PageT", bound="Page")


class Page(Protocol):
    """What :meth:`Message.open` needs of a browser page, e.g. Playwright's."""

    def goto(self, url: str, /) -> Any: ...


class ScreenshotPage(Page, Protocol):
    """What :meth:`Message.screenshot` needs of a browser page, e.g. Playwright's."""

    def screenshot(self, *, path: str | Path | None = ..., full_page: bool = ...) -> bytes: ...


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
    # Checksum name ("MD5", "SHA1", "SHA256") to hex digest; Mailpit 1.29+ only.
    checksums: Mapping[str, str] = field(default_factory=dict, hash=False)
    # The message the attachment belongs to, for MailpitClient.get_attachment().
    message_id: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any], *, message_id: str = "") -> Self:
        return cls(
            part_id=data.get("PartID") or "",
            file_name=data.get("FileName") or "",
            content_type=data.get("ContentType") or "",
            size=data.get("Size") or 0,
            content_id=data.get("ContentID") or "",
            checksums=dict(data.get("Checksums") or {}),
            message_id=message_id,
        )

    def __str__(self) -> str:
        return f"{self.file_name or '(no name)'} ({self.content_type}, {_size(self.size)})"


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

    @property
    def http_link(self) -> str | None:
        """The HTTP(S) unsubscribe link, if the header has one."""
        return next((link for link in self.links if _is_http(link)), None)

    @property
    def mailto_link(self) -> str | None:
        """The mailto: unsubscribe link, if the header has one."""
        return next((link for link in self.links if link.lower().startswith("mailto:")), None)

    @property
    def one_click(self) -> bool:
        """Whether List-Unsubscribe-Post asks for one-click unsubscription (RFC 8058)."""
        return self.header_post.strip().lower() == "list-unsubscribe=one-click"


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
class LinkStatus:
    """One link of Mailpit's link check."""

    url: str
    # 0 when the request failed, e.g. the host does not exist.
    status_code: int
    status: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            url=data.get("URL") or "",
            status_code=data.get("StatusCode") or 0,
            status=data.get("Status") or "",
        )

    @property
    def ok(self) -> bool:
        return 0 < self.status_code < 400

    @property
    def blocked(self) -> bool:
        """Mailpit refused to check it: the address is private or internal (Mailpit 1.29.2+)."""
        return self.status_code == 451 and "private/reserved" in self.status


@dataclass(frozen=True, slots=True)
class LinkCheck:
    """``GET /api/v1/message/{ID}/link-check``: Mailpit's HEAD request to every link."""

    links: tuple[LinkStatus, ...]
    # How many links failed, as Mailpit counts them.
    errors: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            links=tuple(LinkStatus.from_api(item) for item in data.get("Links") or ()),
            errors=data.get("Errors") or 0,
        )

    @property
    def broken(self) -> tuple[LinkStatus, ...]:
        return tuple(link for link in self.links if not link.ok)


@dataclass(frozen=True, slots=True)
class HTMLWarning:
    """An HTML or CSS feature of the message that some email clients do not support."""

    slug: str
    title: str
    description: str
    url: str  # its page on caniemail.com
    category: str  # "html" or "css"
    # How often the message uses it.
    found: int
    # Percentages of the email clients that support it fully, partly or not at all.
    supported: float
    partial: float
    unsupported: float

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        score = data.get("Score") or {}
        return cls(
            slug=data.get("Slug") or "",
            title=data.get("Title") or "",
            description=data.get("Description") or "",
            url=data.get("URL") or "",
            category=data.get("Category") or "",
            found=score.get("Found") or 0,
            supported=score.get("Supported") or 0.0,
            partial=score.get("Partial") or 0.0,
            unsupported=score.get("Unsupported") or 0.0,
        )


@dataclass(frozen=True, slots=True)
class HTMLCheck:
    """``GET /api/v1/message/{ID}/html-check``: how well email clients support the
    message's HTML and CSS, from caniemail.com data."""

    # Percentages of the message's HTML and CSS that email clients support fully,
    # partly or not at all; they add up to 100.
    supported: float
    partial: float
    unsupported: float
    tests: int
    nodes: int
    # The problems, the worst first.
    warnings: tuple[HTMLWarning, ...]
    # Email client families to the platforms Mailpit checked them on.
    platforms: Mapping[str, list[str]] = field(default_factory=dict, hash=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        total = data.get("Total") or {}
        return cls(
            supported=total.get("Supported") or 0.0,
            partial=total.get("Partial") or 0.0,
            unsupported=total.get("Unsupported") or 0.0,
            tests=total.get("Tests") or 0,
            nodes=total.get("Nodes") or 0,
            warnings=tuple(HTMLWarning.from_api(item) for item in data.get("Warnings") or ()),
            platforms=dict(data.get("Platforms") or {}),
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
    # The client that fetched the message, for the checks that ask Mailpit.
    _client: "MailpitClient | None" = field(default=None, compare=False, repr=False, hash=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any], *, client: "MailpitClient | None" = None) -> Self:
        return cls(
            _client=client,
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
            attachments=tuple(
                Attachment.from_api(item, message_id=data["ID"])
                for item in data.get("Attachments") or ()
            ),
            inline=tuple(
                Attachment.from_api(item, message_id=data["ID"])
                for item in data.get("Inline") or ()
            ),
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
        __tracebackhide__ = True
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
        __tracebackhide__ = True
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

    def attachment(
        self,
        name: str | None = None,
        *,
        content_type: str | None = None,
        include_inline: bool = False,
    ) -> Attachment:
        """The one attachment with this file name and content type.

        Both may contain shell-style wildcards (``"invoice-*.pdf"``, ``"image/*"``)
        and match case-insensitively. Inline parts such as embedded images count
        only with ``include_inline``. Raises MailpitAssertionError, a test
        failure, unless exactly one matches. Get the content with
        :meth:`MailpitClient.get_attachment`.
        """
        __tracebackhide__ = True
        candidates = [*self.attachments, *(self.inline if include_inline else ())]
        found = [
            attachment
            for attachment in candidates
            if (name is None or _matches(attachment.file_name, name))
            and (
                content_type is None or _matches(_base_type(attachment.content_type), content_type)
            )
        ]
        if name is not None and len(found) > 1:
            # An exact name wins: as a wildcard, "report[1].pdf" also matches "report1.pdf".
            found = [a for a in found if a.file_name.casefold() == name.casefold()] or found
        if len(found) == 1:
            return found[0]
        wanted = []
        if name is not None:
            wanted.append(f"named {name!r}")
        if content_type is not None:
            wanted.append(f"of type {content_type!r}")
        filters = f" {' and '.join(wanted)}" if wanted else ""
        lines = [f"Expected one attachment{filters} in {self._describe()}, found {len(found)}."]
        if candidates:
            lines.append("Attachments in the message:")
            lines += [f"  {attachment}" for attachment in candidates]
        else:
            lines.append("The message has no attachments.")
        if self.inline and not include_inline:
            # Some mail clients send attachments such as PDFs inline.
            lines.append(
                f"Inline parts, which count with include_inline=True ({len(self.inline)}):"
            )
            lines += [f"  {attachment}" for attachment in self.inline]
        raise MailpitAssertionError("\n".join(lines))

    def unsubscribe_link(self, *, one_click: bool = False) -> str:
        """The HTTP(S) link of the List-Unsubscribe header.

        Raises MailpitAssertionError, a test failure, if the header is missing,
        Mailpit found problems in it, or it has no HTTP(S) link. With
        ``one_click``, the link must also be HTTPS and List-Unsubscribe-Post
        must ask for one-click unsubscription (RFC 8058), as Gmail and Yahoo
        require from bulk senders.
        """
        __tracebackhide__ = True
        unsubscribe = self.list_unsubscribe
        problem = None
        if not unsubscribe.header:
            problem = "has no List-Unsubscribe header"
        elif unsubscribe.errors:
            problem = f"has an invalid List-Unsubscribe header: {unsubscribe.errors}"
        elif unsubscribe.http_link is None:
            problem = f"has no HTTP(S) link in List-Unsubscribe: {unsubscribe.header}"
        elif one_click and not unsubscribe.http_link.lower().startswith("https://"):
            problem = f"has a one-click unsubscribe link that is not HTTPS: {unsubscribe.http_link}"
        elif one_click and not unsubscribe.one_click:
            post = unsubscribe.header_post or "missing"
            problem = (
                "does not offer one-click unsubscription: List-Unsubscribe-Post should be "
                f"'List-Unsubscribe=One-Click', got {post!r}"
            )
        if problem is None and unsubscribe.http_link is not None:
            return unsubscribe.http_link
        raise MailpitAssertionError(f"The {self._describe()} {problem}.")

    def check_links(self, *, follow_redirects: bool = False) -> LinkCheck:
        """Mailpit's link check: a HEAD request to every link in the message."""
        return self._require_client().check_links(self.id, follow_redirects=follow_redirects)

    def assert_links_work(
        self, *, follow_redirects: bool = False, ignore: Iterable[str] = ()
    ) -> LinkCheck:
        """Fail the test if a link in the message is broken, and return the check.

        A link is broken when it answers with an error status (400 and above)
        or not at all. Links containing any of the ``ignore`` strings are not
        held against the message, e.g. social networks that refuse HEAD requests.
        With ``follow_redirects`` the status of the final page counts.
        """
        __tracebackhide__ = True
        ignored = strings(ignore, "parts of links to ignore, e.g. ignore=['linkedin.com']")
        result = self.check_links(follow_redirects=follow_redirects)
        broken = [link for link in result.broken if not any(part in link.url for part in ignored)]
        if not broken:
            return result
        outcomes = [_link_outcome(link) for link in broken]
        width = max(len(outcome) for outcome in outcomes)
        lines = [f"{len(broken)} of {len(result.links)} links in {self._describe()} are broken:"]
        lines += [
            f"  {outcome:<{width}}  {link.url}"
            for outcome, link in zip(outcomes, broken, strict=True)
        ]
        if any(link.blocked for link in broken):
            lines.append(
                "Mailpit refuses to check links to private or internal addresses. To check "
                "links to an application on localhost or in Docker, start Mailpit with "
                "MP_ALLOW_INTERNAL_HTTP_REQUESTS=true (--allow-internal-http-requests)."
            )
        raise MailpitAssertionError("\n".join(lines))

    def check_html(self) -> HTMLCheck:
        """Mailpit's HTML check: how well email clients support the message's HTML and CSS."""
        return self._require_client().check_html(self.id)

    def assert_html_support(self, at_least: float) -> HTMLCheck:
        """Fail the test unless email clients support at least ``at_least`` percent
        of the message's HTML and CSS, and return the check.

        The figure is Mailpit's, from caniemail.com data; its web UI shows the
        same check. A failure lists the worst problems.
        """
        __tracebackhide__ = True
        if not self.html.strip():
            raise MailpitAssertionError(f"The {self._describe()} has no HTML part to check.")
        result = self.check_html()
        if result.supported >= at_least:
            return result
        lines = [
            f"Email clients support {result.supported:.1f}% of the HTML and CSS in "
            f"{self._describe()}, expected at least {at_least:g}%."
        ]
        if result.warnings:
            lines.append("Worst problems (caniemail.com data):")
            lines += [
                f"  {warning.title}: {warning.unsupported:.0f}% of clients do not support it, "
                f"{warning.partial:.0f}% partly; used {warning.found}x  {warning.url}"
                for warning in result.warnings[:5]
            ]
        raise MailpitAssertionError("\n".join(lines))

    def open(self, page: PageT) -> PageT:
        """Show the message's HTML in a browser page, as its recipient would see it,
        and return the page, e.g. to click a link in it.

        The page is Mailpit's rendering of the HTML part, inline images included;
        it works with a Playwright ``Page`` or anything else with ``goto(url)``.
        If Mailpit asks for a password, give the browser context its
        ``http_credentials``. Raises MailpitAssertionError, a test failure, if
        the message has no HTML part or Mailpit answers with an error, such as
        401 without credentials or 404 for a message deleted meanwhile.

        The page must be sync. With an async Playwright page, open the message
        with ``await page.goto(mailpit_async.html_url(message.id))``.
        """
        __tracebackhide__ = True
        if not self.html.strip():
            raise MailpitAssertionError(f"The {self._describe()} has no HTML part to open.")
        url = self._require_client().html_url(self.id)
        response = page.goto(url)
        if inspect.isawaitable(response):
            # The navigation never happens; close the coroutine so it is not "never awaited".
            getattr(response, "close", lambda: None)()
            raise TypeError(
                "Message.open() and screenshot() need a sync page. With an async page: "
                "await page.goto(mailpit_async.html_url(message.id))"
            )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 400:
            raise MailpitAssertionError(_page_error(self._describe(), url, status))
        return page

    def screenshot(self, page: ScreenshotPage, *, path: str | Path | None = None) -> bytes:
        """Open the message in ``page`` and return a PNG of the whole of it,
        also saved to ``path`` if given, e.g. for visual comparison."""
        __tracebackhide__ = True
        self.open(page)
        return page.screenshot(path=path, full_page=True)

    def _require_client(self) -> "MailpitClient":
        if self._client is None:
            raise ValueError(
                "The message was not fetched by a MailpitClient; "
                "ask the client with the message's ID instead"
            )
        return self._client

    def _links(self) -> list[Link]:
        return find_links(self.text, self.html)

    def _describe(self) -> str:
        # A newsletter's To may be empty, with its readers in Bcc.
        for field_name, addresses in (("", self.to), ("cc ", self.cc), ("bcc ", self.bcc)):
            if addresses:
                recipients = ", ".join(address.address for address in addresses)
                return f"message {self.subject!r} to {field_name}{recipients}"
        return f"message {self.subject!r} to no one"


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


def _matches(value: str, pattern: str) -> bool:
    # The exact name first: in a wildcard, "[1]" of "report[1].pdf" is a character class.
    value, pattern = value.casefold(), pattern.casefold()
    return value == pattern or fnmatch.fnmatchcase(value, pattern)


def _page_error(message: str, url: str, status: int) -> str:
    """Why a browser could not open a message in Mailpit."""
    error = f"Mailpit answered {url} with HTTP {status}, so the browser shows no {message}."
    if status == 401:
        error += " Give the browser context Mailpit's http_credentials."
    elif status == 404:
        error += " The message was deleted meanwhile, by a cleanup or MP_MAX_MESSAGES."
    return error


def _base_type(content_type: str) -> str:
    """ "text/plain; charset=utf-8" -> "text/plain" """
    return content_type.split(";", 1)[0].strip()


def _is_http(link: str) -> bool:
    return link.lower().startswith(("http://", "https://"))


def _size(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB"
    return f"{size / 1_000_000:.1f} MB"


def _link_outcome(link: LinkStatus) -> str:
    """ "404 Not Found", or the error when the request failed."""
    return f"{link.status_code} {link.status}" if link.status_code else link.status or "no answer"


def _describe_link(link: Link) -> str:
    if not link.texts:
        return link.url
    return f"{link.url}  (text: {', '.join(repr(text) for text in link.texts)})"


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


@dataclass(frozen=True, slots=True)
class ChaosTrigger:
    """An SMTP error that Mailpit's Chaos returns on purpose, and how often."""

    # The SMTP reply code, from 400 to 599.
    error_code: int
    # The chance of the error for each SMTP command, in percent: 0 is never, 100 always.
    probability: int = 0

    def __post_init__(self) -> None:
        # Checked here, before Mailpit sees it: it applies the triggers one by one and
        # stops at an invalid one, so a bad trigger leaves the others half changed.
        if not 400 <= self.error_code <= 599:
            raise ValueError(
                f"code must be an SMTP error code from 400 to 599, got {self.error_code!r}"
            )
        if not 0 <= self.probability <= 100:
            raise ValueError(
                f"probability must be a percentage from 0 to 100, got {self.probability!r}"
            )

    @property
    def active(self) -> bool:
        return self.probability > 0

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None, *, default_code: int) -> Self:
        data = data or {}
        return cls(
            error_code=data.get("ErrorCode") or default_code,
            probability=data.get("Probability") or 0,
        )

    def to_api(self) -> dict[str, int]:
        return {"ErrorCode": self.error_code, "Probability": self.probability}


# Mailpit's error codes when a trigger has none: 451 "try again later", 535 "authentication failed".
_NO_SENDER_ERRORS = ChaosTrigger(451)
_NO_RECIPIENT_ERRORS = ChaosTrigger(451)
_NO_AUTHENTICATION_ERRORS = ChaosTrigger(535)


@dataclass(frozen=True, slots=True)
class ChaosTriggers:
    """``/api/v1/chaos``: the SMTP errors Mailpit returns on purpose.

    ``sender`` fails ``MAIL FROM``, ``recipient`` fails ``RCPT TO`` and
    ``authentication`` fails ``AUTH``. ``ChaosTriggers()`` has every error off.
    """

    sender: ChaosTrigger = _NO_SENDER_ERRORS
    recipient: ChaosTrigger = _NO_RECIPIENT_ERRORS
    authentication: ChaosTrigger = _NO_AUTHENTICATION_ERRORS

    @property
    def active(self) -> bool:
        return self.sender.active or self.recipient.active or self.authentication.active

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            sender=ChaosTrigger.from_api(data.get("Sender"), default_code=451),
            recipient=ChaosTrigger.from_api(data.get("Recipient"), default_code=451),
            authentication=ChaosTrigger.from_api(data.get("Authentication"), default_code=535),
        )

    def to_api(self) -> dict[str, dict[str, int]]:
        return {
            "Sender": self.sender.to_api(),
            "Recipient": self.recipient.to_api(),
            "Authentication": self.authentication.to_api(),
        }


def _addresses(data: Any) -> tuple[Address, ...]:
    return tuple(Address.from_api(item) for item in data or ())
