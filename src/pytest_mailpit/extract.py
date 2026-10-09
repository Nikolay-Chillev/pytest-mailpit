"""Find links and one-time codes in the body of a message."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

# A URL in plain text ends at whitespace, angle brackets, quotes (typographic ones
# too, as in „https://...“ or «https://...»), an em dash, an ellipsis or a zero-width space.
_URL_IN_TEXT = re.compile(
    r"https?://[^\s<>\"'`\u201c\u201d\u201e\u2018\u2019\u00ab\u00bb\u2014\u2026\u200b]+",
    re.IGNORECASE,
)
# Sentence punctuation right after a URL is not part of it.
_TRAILING_PUNCTUATION = ".,;:!?)]}*"

# 4-8 digits, or two groups of 3-4 digits split by a space or hyphen ("123 456").
# Not a code: digits glued to letters, signs or other numbers (dates, times,
# amounts, phone numbers such as "+359 2 123 4567"); after a currency sign, "#"
# or "№" ("$1299", "#10023"); after ") " (the "(800) 555-0199" of a phone
# number, "(c) 2026"); after "7, " ("October 7, 2026"); and before a currency
# or a unit ("1500 лв.", "1440 minutes", "2026 г.").
_CODE = re.compile(
    r"(?<![\w+-])(?<!\d[.,/: -])(?<![$€£¥₹₽#№])(?<!\))(?<!\)\s)(?<!\d,\s)"
    r"(\d{4,8}|\d{3,4}[ -]\d{3,4})"
    r"(?![\w-])(?![.,/: -]\d)"
    r"(?!\s?(?:[$€£¥₹₽%]|(?i:"
    r"lv|лв|лева|eur|euro|usd|bgn|gbp|chf|ron|pln|kr|"
    r"min|mins|minutes?|hours?|hrs?|days?|weeks?|months?|years?|seconds?|secs?|"
    r"мин|минути|минута|час|часа|дни|ден|седмици|месеца|години|секунди|г)\b))"
)
# A year, which is not a code when the message has any other candidate.
_YEAR = re.compile(r"(?:19|20)\d\d")
# A label right before a number that is a reference, not a code: "Reference: 77812345".
_LABEL_BEFORE = re.compile(
    r"(?:reference|ref|order|invoice|account|ticket|booking|customer|номер|поръчка|фактура|"
    r"резервация|клиент)\w*\s*(?:no\.?|nr\.?|number)?\s*[:#№]?\s*$",
    re.IGNORECASE,
)
# Words that usually stand next to a one-time code.
_CODE_KEYWORD = re.compile(
    r"\b(?:codes?|otp|one[- ]time|verif\w*|passcode|pin|token|код\w*)\b", re.IGNORECASE
)
# How far a code may be from a keyword, in characters, to count as next to it.
_KEYWORD_DISTANCE = 80
# How many lines, blank ones not counted, a code on a line of its own may be from a keyword.
_KEYWORD_LINES = 2


@dataclass(frozen=True, slots=True)
class Link:
    url: str
    # The visible texts of the HTML links to the URL, in order; none for a URL
    # that is only in the text part.
    texts: tuple[str, ...] = ()


def find_links(text: str, html: str) -> list[Link]:
    """The http(s) links of a message: from the HTML first, then the text part.

    HTML entities such as ``&amp;`` in ``href`` are decoded, and an image's alt
    text counts as the text of the link around it. A URL that occurs more than
    once is returned once, with every text found for it: a logo and a button
    often link to the same page.
    """
    texts: dict[str, list[str]] = {}
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    for url, link_text in parser.links:
        found = texts.setdefault(url, [])
        if link_text and link_text not in found:
            found.append(link_text)
    for match in _URL_IN_TEXT.finditer(text):
        texts.setdefault(_trim(match.group()), [])
    return [Link(url, tuple(found)) for url, found in texts.items() if _is_http(url)]


def filter_links(
    links: list[Link],
    *,
    contains: str | None = None,
    pattern: str | re.Pattern[str] | None = None,
    text: str | None = None,
) -> list[Link]:
    """Keep the links whose URL contains ``contains`` and matches ``pattern``
    (a regular expression searched in the URL), and one of whose visible texts
    contains ``text`` (case-insensitive)."""
    if contains is not None:
        links = [link for link in links if contains in link.url]
    if pattern is not None:
        links = [link for link in links if re.search(pattern, link.url)]
    if text is not None:
        wanted = text.casefold()
        links = [link for link in links if any(wanted in t.casefold() for t in link.texts)]
    return links


def find_codes(text: str, html: str, *, pattern: str | re.Pattern[str] | None = None) -> list[str]:
    """One-time codes in a message, the most likely first.

    Without ``pattern``, codes are runs of 4-8 digits (or "123 456" / "123-456",
    returned without the separator) that are not part of a URL, date, time,
    amount, phone number or duration. When words such as "code", "OTP",
    "verification" or "код" are present, the codes next to them count: on the
    same line, or on a line of their own right before or after, closest first;
    failing that, the codes within 80 characters. A year counts only when there
    is nothing else.

    With ``pattern``, every match of the regular expression is returned (its
    first group, if it has groups), in the order of the message.

    The text part is searched first, and the HTML when the text part has no
    code, e.g. when it only says to open the email in an HTML client.
    """
    for body in (text, html_to_text(html)):
        # Numbers inside links are order or user IDs, not codes; a pattern may look
        # for a token in a link, though.
        found = _find_codes(body if pattern is not None else _URL_IN_TEXT.sub(" ", body), pattern)
        if found:
            return found
    return []


def _find_codes(body: str, pattern: str | re.Pattern[str] | None) -> list[str]:
    if pattern is not None:
        regex = re.compile(pattern)
        found = [
            match.group(1) if regex.groups else match.group() for match in regex.finditer(body)
        ]
        return list(dict.fromkeys(code for code in found if code is not None))
    codes = _codes_by_lines(body) or _codes_by_distance(body)
    others = [code for code in codes if not _YEAR.fullmatch(code)]
    return list(dict.fromkeys(others or codes))


def _codes_by_lines(body: str) -> list[str]:
    """The codes on a line with a keyword, near it, or alone on a line next to one."""
    lines = [line for line in body.splitlines() if line.strip()]
    keyword_lines = [i for i, line in enumerate(lines) if _CODE_KEYWORD.search(line)]
    ranked: list[tuple[int, int, int, int, str]] = []
    for i, line in enumerate(lines):
        for match in _CODE.finditer(line):
            if _LABEL_BEFORE.search(line[: match.start()]):
                continue
            code = re.sub(r"[ -]", "", match.group(1))
            if i in keyword_lines:
                distance = min(abs(match.start() - k.start()) for k in _CODE_KEYWORD.finditer(line))
                if distance <= _KEYWORD_DISTANCE:
                    ranked.append((0, distance, i, match.start(), code))
            elif line.strip(" \t:.*") == match.group(1) and keyword_lines:
                away = min(abs(i - k) for k in keyword_lines)
                if away <= _KEYWORD_LINES:
                    ranked.append((1, away, i, match.start(), code))
    return [code for *_, code in sorted(ranked)]


def _codes_by_distance(body: str) -> list[str]:
    """The codes within reach of a keyword, closest first; all codes if no keyword is near."""
    candidates = [
        (match.start(), re.sub(r"[ -]", "", match.group(1)))
        for match in _CODE.finditer(body)
        if not _LABEL_BEFORE.search(body[: match.start()])
    ]
    keywords = [match.start() for match in _CODE_KEYWORD.finditer(body)]
    near: list[str] = []
    if keywords:
        by_distance = sorted(
            (min(abs(position - keyword) for keyword in keywords), position, code)
            for position, code in candidates
        )
        near = [code for distance, _, code in by_distance if distance <= _KEYWORD_DISTANCE]
    return near or [code for _, code in candidates]


def html_to_text(html: str) -> str:
    """The visible text of an HTML document, without scripts and styles.

    Blocks such as paragraphs and table cells end lines, so that what sits in
    different blocks never reads as one sentence or one number.
    """
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _trim(url: str) -> str:
    """A URL found in text without the punctuation after it; ")" stays if it closes "("."""
    while url and url[-1] in _TRAILING_PUNCTUATION:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def _is_http(url: str) -> bool:
    try:
        return urlsplit(url).scheme in ("http", "https")
    except ValueError:  # e.g. a template placeholder such as https://[unsubscribe_url]
        return False


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "img" and self._href is not None:
            self._text.append(f" {attributes.get('alt') or ''} ")
        if tag not in ("a", "area"):
            return
        href = (attributes.get("href") or "").strip()
        if tag == "area":
            self.links.append((href, attributes.get("alt") or ""))
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
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


class _TextParser(HTMLParser):
    _HIDDEN = frozenset({"script", "style", "head", "title"})
    # Tags that end a line of text.
    _BREAKS = frozenset(
        {
            "address",
            "article",
            "blockquote",
            "br",
            "center",
            "dd",
            "div",
            "dl",
            "dt",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hr",
            "li",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "tbody",
            "td",
            "tfoot",
            "th",
            "thead",
            "tr",
            "ul",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self._hidden = 0  # a <head> left open ends here
        elif tag in self._HIDDEN:
            self._hidden += 1
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:  # a line break in the HTML source is only a space
            self.parts.append(" ".join(data.splitlines()))
