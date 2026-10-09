"""Build search queries in Mailpit's syntax.

Mailpit splits a query on spaces outside double quotes and then drops every
double quote. A value can therefore contain spaces but never a double quote,
and there is no way to escape one. A term that starts with ``-`` or ``!`` is
negated, quoted or not.

Terms match as substrings: ``to:a@example.test`` also finds
``ba@example.test``, so check the exact address on the results when that
matters. ``tag:`` is the exception: it matches a whole tag. Case is ignored in
ASCII letters only, not in Cyrillic, for example. Up to Mailpit 1.31.4, ``_``
and ``%`` in a term are wildcards: ``subject:Order_1`` also finds "Order-1".
"""

# Mailpit's filters, the same in every supported version: a term that starts
# with one of the prefixes, or is one of the keywords, is a filter, quoted or not.
_PREFIXES = (
    "addressed:",
    "after:",
    "bcc:",
    "before:",
    "cc:",
    "from:",
    "larger:",
    "message-id:",
    "reply-to:",
    "smaller:",
    "subject:",
    "tag:",
    "to:",
)
_KEYWORDS = frozenset(
    {
        "has:attachment",
        "has:attachments",
        "has:inline",
        "has:inlines",
        "is:read",
        "is:tagged",
        "is:unread",
    }
)
# Filters whose value Mailpit drops unless it holds a date or a size.
_NUMERIC = ("after:", "before:", "larger:", "smaller:")

# Keyword argument of build_query() to Mailpit's filter name.
_FILTERS = {
    "addressed": "addressed",
    "to": "to",
    "sender": "from",
    "cc": "cc",
    "bcc": "bcc",
    "reply_to": "reply-to",
    "subject": "subject",
    "message_id": "message-id",
    "tag": "tag",
}


def quote(value: str) -> str:
    """Quote ``value`` for a search, so that it may contain spaces."""
    if '"' in value:
        raise ValueError(f"Mailpit's search syntax cannot express a double quote: {value!r}")
    if not value.strip():
        raise ValueError("A search value must not be empty")
    return f'"{value}"'


def build_query(
    *text: str,
    addressed: str | None = None,
    to: str | None = None,
    sender: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to: str | None = None,
    subject: str | None = None,
    message_id: str | None = None,
    tag: str | None = None,
) -> str:
    """Build a query that matches messages meeting every given criterion.

    ``text`` terms are searched in the whole message. ``sender`` filters on the
    From header. ``addressed`` matches any of From, To, Cc, Bcc and Reply-To.
    """
    terms = []
    for term in text:
        if term.lstrip().startswith(("-", "!")):
            raise ValueError(f"A text term starting with - or ! would negate the search: {term!r}")
        lowered = term.strip().lower()
        if lowered in _KEYWORDS or lowered.startswith(_PREFIXES):
            # Mailpit drops the quotes before it looks for filters.
            raise ValueError(
                f"Mailpit would read the text term {term!r} as a filter; "
                "use a keyword argument such as sender= or subject= instead"
            )
        terms.append(quote(term))
    criteria = {
        "addressed": addressed,
        "to": to,
        "sender": sender,
        "cc": cc,
        "bcc": bcc,
        "reply_to": reply_to,
        "subject": subject,
        "message_id": message_id,
        "tag": tag,
    }
    terms += [
        f"{_FILTERS[name]}:{quote(value)}" for name, value in criteria.items() if value is not None
    ]
    if not terms:
        raise ValueError("A search needs at least one criterion")
    return " ".join(terms)


def narrows(query: str) -> bool:
    """Whether Mailpit keeps at least one term of ``query``.

    Mailpit silently drops a term with nothing to search for: a filter with an
    empty value (``to:``, ``tag:""``), a date or size it cannot read
    (``after:soon``), or a term without a letter or digit (``()``). A query of
    such terms matches every message.
    """
    for term in _terms(query):
        lowered = term.lower()
        if lowered[:1] in ("-", "!"):
            lowered = lowered[1:]
        if lowered in _KEYWORDS:
            return True
        prefix = next((prefix for prefix in _PREFIXES if lowered.startswith(prefix)), "")
        value = lowered[len(prefix) :]
        wanted = str.isdigit if prefix in _NUMERIC else str.isalnum
        if any(wanted(char) for char in value):
            return True
    return False


def _terms(query: str) -> list[str]:
    """The terms of a query as Mailpit reads them: split on spaces outside double
    quotes, then the quotes dropped."""
    terms: list[str] = []
    current: list[str] = []
    quoted = False
    for char in query:
        if char == '"':
            quoted = not quoted
        elif char.isspace() and not quoted:
            terms.append("".join(current))
            current = []
        else:
            current.append(char)
    terms.append("".join(current))
    return [term for term in terms if term]
