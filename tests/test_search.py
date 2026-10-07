import pytest

from pytest_mailpit import build_query, quote


def test_quote_allows_spaces() -> None:
    assert quote("Order confirmed") == '"Order confirmed"'


@pytest.mark.parametrize("value", ['say "hi"', '"'])
def test_quote_rejects_double_quotes_mailpit_cannot_express(value: str) -> None:
    with pytest.raises(ValueError, match="double quote"):
        quote(value)


@pytest.mark.parametrize("value", ["", "   "])
def test_quote_rejects_empty_values(value: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        quote(value)


def test_build_query_maps_every_criterion_to_mailpit_filters() -> None:
    query = build_query(
        to="a@example.test",
        sender="shop@example.test",
        cc="c@example.test",
        bcc="b@example.test",
        reply_to="r@example.test",
        subject="Order 1001",
        message_id="m-1@example.test",
        tag="orders",
    )

    assert query == (
        'to:"a@example.test" from:"shop@example.test" cc:"c@example.test" bcc:"b@example.test" '
        'reply-to:"r@example.test" subject:"Order 1001" message-id:"m-1@example.test" tag:"orders"'
    )


def test_build_query_quotes_text_terms() -> None:
    assert build_query("reset your password", to="a@example.test") == (
        '"reset your password" to:"a@example.test"'
    )


@pytest.mark.parametrize("term", ["-draft", "!draft", " -draft"])
def test_build_query_rejects_text_that_mailpit_would_read_as_negation(term: str) -> None:
    with pytest.raises(ValueError, match="negate"):
        build_query(term)


def test_build_query_needs_a_criterion() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_query()
