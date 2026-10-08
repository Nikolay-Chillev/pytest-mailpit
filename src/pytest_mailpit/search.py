"""Build search queries in Mailpit's syntax.

Mailpit splits a query on spaces outside double quotes and then drops every
double quote. A value can therefore contain spaces but never a double quote,
and there is no way to escape one. A term that starts with ``-`` or ``!`` is
negated, quoted or not.

Terms match as substrings, case-insensitively: ``to:a@example.test`` also
finds ``ba@example.test``. Check the exact address on the results when that
matters.
"""

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
