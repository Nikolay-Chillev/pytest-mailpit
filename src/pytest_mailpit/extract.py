"""Find links and one-time codes in the body of a message."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

# A URL in plain text ends at whitespace, angle brackets or quotes.
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
# Sentence punctuation right after a URL is not part of it.
_TRAILING_PUNCTUATION = ".,;:!?)]}*"

# 4-8 digits, or two groups of 3-4 digits split by a space or hyphen ("123 456").
# Digits glued to letters, signs or other numbers are not codes: dates, times,
# amounts, and phone numbers such as "+359 2 123 4567".
_CODE = re.compile(r"(?<![\w+-])(?<!\d[.,/: -])(\d{4,8}|\d{3,4}[ -]\d{3,4})(?![\w-])(?![.,/: -]\d)")
# Words that usually stand next to a one-time code.
_CODE_KEYWORD = re.compile(
    r"\b(?:codes?|otp|one[- ]time|verif\w*|passcode|pin|token|код\w*)\b", re.IGNORECASE
)
# How far a code may be from a keyword, in characters, to count as next to it.
_KEYWORD_DISTANCE = 80


@dataclass(frozen=True, slots=True)
class Link:
    url: str
    # The visible text of an HTML link; empty for links found in plain text.
    text: str = ""


def find_links(text: str, html: str) -> list[Link]:
    """The http(s) links of a message: from the HTML first, then the text part.

    HTML entities such as ``&amp;`` in ``href`` are decoded. A URL that occurs
    more than once is returned once, with the first link text found for it.
    """
    links: dict[str, Link] = {}
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    for link in parser.links:
        links.setdefault(link.url, link)
    for match in _URL_IN_TEXT.finditer(text):
        url = match.group().rstrip(_TRAILING_PUNCTUATION)
        links.setdefault(url, Link(url))
    return [link for link in links.values() if urlsplit(link.url).scheme in ("http", "https")]


def filter_links(
    links: list[Link],
    *,
    contains: str | None = None,
    pattern: str | re.Pattern[str] | None = None,
    text: str | None = None,
) -> list[Link]:
    """Keep the links whose URL contains ``contains`` and matches ``pattern``
    (a regular expression searched in the URL), and whose visible text contains
    ``text`` (case-insensitive)."""
    if contains is not None:
        links = [link for link in links if contains in link.url]
    if pattern is not None:
        links = [link for link in links if re.search(pattern, link.url)]
    if text is not None:
        wanted = text.casefold()
        links = [link for link in links if wanted in link.text.casefold()]
    return links


def find_codes(text: str, html: str, *, pattern: str | re.Pattern[str] | None = None) -> list[str]:
    """One-time codes in a message, the most likely first.

    Without ``pattern``, codes are runs of 4-8 digits (or "123 456" / "123-456",
    returned without the separator) that are not part of a URL, date, time or
    amount. When words such as "code", "OTP", "verification" or "код" are
    present, only the codes near them are returned, closest first; if none is
    near, all codes are returned in the order of the message.

    With ``pattern``, every match of the regular expression is returned (its
    first group, if it has groups), in the order of the message.

    The text part is searched; the HTML only when the message has no text part.
    """
    body = text if text.strip() else html_to_text(html)
    # Numbers inside links are order or user IDs, not codes.
    body = _URL_IN_TEXT.sub(" ", body)
    if pattern is not None:
        regex = re.compile(pattern)
        found = [
            match.group(1) if regex.groups else match.group() for match in regex.finditer(body)
        ]
        return list(dict.fromkeys(found))

    candidates = [
        (match.start(), re.sub(r"[ -]", "", match.group(1))) for match in _CODE.finditer(body)
    ]
    keywords = [match.start() for match in _CODE_KEYWORD.finditer(body)]
    near: list[str] = []
    if keywords:
        by_distance = sorted(
            (min(abs(position - keyword) for keyword in keywords), position, code)
            for position, code in candidates
        )
        near = [code for distance, _, code in by_distance if distance <= _KEYWORD_DISTANCE]
    codes = near or [code for _, code in candidates]
    return list(dict.fromkeys(codes))


def html_to_text(html: str) -> str:
    """The visible text of an HTML document, without scripts and styles."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("a", "area"):
            return
        href = (dict(attrs).get("href") or "").strip()
        if tag == "area":
            self.links.append(Link(href, dict(attrs).get("alt") or ""))
        else:
            self._finish()  # an unclosed <a> ends where the next one starts
            self._href, self._text = href, []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._finish()

    def close(self) -> None:
        super().close()
        self._finish()

    def _finish(self) -> None:
        if self._href is not None:
            self.links.append(Link(self._href, " ".join("".join(self._text).split())))
            self._href = None


class _TextParser(HTMLParser):
    _HIDDEN = frozenset({"script", "style", "head", "title"})
    # Tags after which the following text starts a new word.
    _BREAKS = frozenset(
        {"br", "p", "div", "td", "th", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag in self._BREAKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BREAKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)
