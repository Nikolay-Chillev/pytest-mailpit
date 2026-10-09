import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import responses
from responses import matchers

from pytest_mailpit import (
    MailpitAssertionError,
    MailpitClient,
    MailpitConnectionError,
    MailpitError,
)
from tests import samples

URL = "http://mailpit.test:8025/"
SEARCH = f"{URL}api/v1/search"


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def client() -> MailpitClient:
    return MailpitClient(URL, wait_timeout=0.3, poll_interval=0.02)


def summary(
    message_id: str,
    *,
    to: str = "ivan@example.test",
    cc: str | None = None,
    sender: str = "orders@shop.example.test",
    subject: str = "Hello",
    created: str = "2026-10-07T11:22:33Z",
) -> dict[str, Any]:
    return samples.SUMMARY | {
        "ID": message_id,
        "To": [{"Name": "", "Address": to}],
        "Cc": [{"Name": "", "Address": cc}] if cc else [],
        "Bcc": [],
        "From": {"Name": "", "Address": sender},
        "Subject": subject,
        "Created": created,
    }


def page(*summaries: dict[str, Any]) -> dict[str, Any]:
    return samples.MESSAGE_LIST | {"messages_count": len(summaries), "messages": list(summaries)}


def register_messages(mocked: responses.RequestsMock, *ids: str) -> None:
    for message_id in ids:
        mocked.get(f"{URL}api/v1/message/{message_id}", json=samples.MESSAGE | {"ID": message_id})


def search_calls(mocked: responses.RequestsMock) -> int:
    return len([call for call in mocked.calls if (call.request.url or "").startswith(SEARCH)])


# Waiting for messages


def test_waits_until_the_message_arrives(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page())
    mocked.get(SEARCH, json=page())
    mocked.get(SEARCH, json=page(summary("m1")))
    register_messages(mocked, "m1")

    message = client.wait_for_message(recipient="ivan@example.test")

    assert message.id == "m1"
    assert search_calls(mocked) == 3


def test_criteria_become_a_mailpit_search(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    query = (
        'tag:"orders" addressed:"ivan@example.test" from:"orders@shop.example.test" subject:"Hi"'
    )
    mocked.get(
        SEARCH,
        json=page(summary("m1")),
        match=[matchers.query_param_matcher({"query": query, "start": 0, "limit": 250})],
    )
    register_messages(mocked, "m1")

    client.wait_for_message(
        'tag:"orders"',
        recipient="ivan@example.test",
        sender="orders@shop.example.test",
        subject="Hi",
    )


def test_recipient_must_match_the_whole_address(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    # Mailpit's search matches substrings, so it also returns the message to "ba@x.test".
    mocked.get(SEARCH, json=page(summary("other", to="ba@x.test")))
    mocked.get(SEARCH, json=page(summary("mine", to="A@X.test"), summary("other", to="ba@x.test")))
    register_messages(mocked, "mine")

    assert client.wait_for_message(recipient="a@x.test").id == "mine"


def test_recipient_can_be_in_cc(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.get(SEARCH, json=page(summary("m1", to="someone@x.test", cc="a@x.test")))
    register_messages(mocked, "m1")

    assert client.wait_for_message(recipient="a@x.test").id == "m1"


def test_sender_must_match_the_whole_address(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(
        SEARCH,
        json=page(summary("m2", sender="no-reply@x.test"), summary("m1", sender="reply@x.test")),
    )
    register_messages(mocked, "m1")

    assert client.wait_for_message(sender="reply@x.test").id == "m1"


def test_since_skips_older_messages(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.get(
        SEARCH,
        json=page(
            summary("new", created="2026-10-07T11:00:01Z"),
            summary("old", created="2026-10-07T10:59:59Z"),
        ),
    )
    register_messages(mocked, "new")

    message = client.wait_for_message(
        recipient="ivan@example.test", since=datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    )

    assert message.id == "new"


def test_wait_for_messages_returns_them_oldest_first(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page(summary("m1", created="2026-10-07T11:00:00Z")))
    mocked.get(
        SEARCH,
        json=page(
            summary("m2", created="2026-10-07T11:00:05Z"),
            summary("m1", created="2026-10-07T11:00:00Z"),
        ),
    )
    register_messages(mocked, "m1", "m2")

    messages = client.wait_for_messages(2, recipient="ivan@example.test")

    assert [message.id for message in messages] == ["m1", "m2"]


# Failures


def search_for(query: str) -> list[Any]:
    return [matchers.query_param_matcher({"query": query, "start": 0, "limit": 250})]


def test_timeout_lists_what_arrived_for_the_recipient(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page(), match=search_for('addressed:"a@x.test" subject:"Reset"'))
    mocked.get(
        SEARCH,
        json=page(
            summary("other", to="ba@x.test", subject="Not mine"),
            summary("mine", to="a@x.test", subject="Welcome", created="2026-10-07T11:22:33Z"),
        ),
        match=search_for('addressed:"a@x.test"'),
    )

    with pytest.raises(MailpitAssertionError) as raised:
        client.wait_for_message(recipient="a@x.test", subject="Reset")

    assert str(raised.value) == (
        'Expected 1 message matching addressed:"a@x.test" subject:"Reset" within 0.3s, '
        "none arrived.\n"
        "Messages to a@x.test (1):\n"
        "  Received (UTC)  To        Subject\n"
        "  11:22:33        a@x.test  Welcome"
    )


def test_timeout_lists_the_newest_messages_when_none_went_to_the_recipient(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page())
    mocked.get(
        f"{URL}api/v1/messages",
        json=page(
            summary("new", to="other@x.test", subject="Second", created="2026-10-07T11:22:34Z"),
            summary("old", to="other@x.test", subject="First", created="2026-10-07T11:22:33Z"),
        )
        | {"total": 7},
    )

    with pytest.raises(MailpitAssertionError) as raised:
        client.wait_for_message(recipient="a@x.test")

    assert str(raised.value).endswith(
        "none arrived.\n"
        "No messages to a@x.test. Newest messages in Mailpit (2 of 7):\n"
        "  Received (UTC)  To            Subject\n"
        "  11:22:33        other@x.test  First\n"
        "  11:22:34        other@x.test  Second"
    )


def test_timeout_shows_at_most_ten_of_the_recipients_messages(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page(), match=search_for('addressed:"a@x.test" subject:"Reset"'))
    newest_first = [
        summary(f"m{n}", to="a@x.test", subject=f"Mail {n}", created=f"2026-10-07T11:00:{n:02}Z")
        for n in range(12, 0, -1)
    ]
    mocked.get(SEARCH, json=page(*newest_first), match=search_for('addressed:"a@x.test"'))

    with pytest.raises(MailpitAssertionError) as raised:
        client.wait_for_message(recipient="a@x.test", subject="Reset")

    lines = str(raised.value).splitlines()
    assert lines[1] == "Messages to a@x.test (12, newest 10 shown):"
    assert [line.split()[-1] for line in lines[3:]] == [str(n) for n in range(3, 13)]


def test_timeout_says_how_many_of_several_arrived(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page(summary("m1")))
    mocked.get(f"{URL}api/v1/messages", json=page())

    with pytest.raises(
        MailpitAssertionError,
        match=r"Expected 2 messages matching tag:\"x\" within 0\.1s, 1 arrived\.\n"
        r"Mailpit has no messages\.",
    ):
        client.wait_for_messages(2, tag="x", timeout=0.1)


def test_timeout_still_reports_when_the_messages_cannot_be_listed(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page())

    with pytest.raises(MailpitAssertionError, match="Could not list the messages in Mailpit"):
        client.wait_for_message(tag="x", timeout=0)


def test_more_messages_than_expected_fail_at_once(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(
        SEARCH,
        json=page(
            summary("m2", subject="Reset (2)", created="2026-10-07T11:00:05Z"),
            summary("m1", subject="Reset (1)", created="2026-10-07T11:00:00Z"),
        ),
    )

    with pytest.raises(MailpitAssertionError) as raised:
        client.wait_for_message(recipient="ivan@example.test", timeout=60)

    assert str(raised.value) == (
        'Expected 1 message matching addressed:"ivan@example.test", found 2:\n'
        "  Received (UTC)  To                 Subject\n"
        "  11:00:00        ivan@example.test  Reset (1)\n"
        "  11:00:05        ivan@example.test  Reset (2)"
    )


def test_assertion_errors_are_test_failures() -> None:
    assert issubclass(MailpitAssertionError, AssertionError)
    assert issubclass(MailpitAssertionError, MailpitError)


def test_connection_errors_are_not_mistaken_for_a_missing_message(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    # Nothing is registered, so the mock refuses the connection.
    with pytest.raises(MailpitConnectionError) as raised:
        client.wait_for_message(recipient="a@x.test")

    assert not isinstance(raised.value, AssertionError)


# Expecting no message


def test_assert_no_message_waits_the_whole_window(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page())
    started = time.monotonic()

    client.assert_no_message(recipient="a@x.test", within=0.1)

    assert time.monotonic() - started >= 0.1
    assert search_calls(mocked) >= 2


def test_assert_no_message_fails_as_soon_as_one_arrives(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page())
    mocked.get(SEARCH, json=page(summary("m1", to="a@x.test", subject="Oops")))

    with pytest.raises(MailpitAssertionError) as raised:
        client.assert_no_message(recipient="a@x.test", within=60)

    assert str(raised.value) == (
        'Expected no message matching addressed:"a@x.test", found 1:\n'
        "  Received (UTC)  To        Subject\n"
        "  11:22:33        a@x.test  Oops"
    )


def test_assert_no_message_shows_since_in_utc(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(SEARCH, json=page(summary("m1", created="2026-10-07T11:00:00Z")))
    since = datetime.fromisoformat("2026-10-07T13:59:00+03:00")

    with pytest.raises(MailpitAssertionError, match=r'tag:"x" since 10:59:00 UTC, found 1'):
        client.assert_no_message(tag="x", since=since)


# Arguments


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda c: c.wait_for_message(), "Give a query, or at least one of"),
        (lambda c: c.wait_for_message(" "), "must not be empty"),
        (lambda c: c.wait_for_message(tag="x", since=datetime(2026, 1, 1)), "timezone-aware"),
        (lambda c: c.wait_for_messages(0, tag="x"), "use assert_no_message"),
        (lambda c: c.wait_for_message(tag="x", timeout=-1), "timeout must not be negative"),
        (lambda c: c.assert_no_message(tag="x", within=-1), "within must not be negative"),
    ],
)
def test_invalid_arguments(client: MailpitClient, call: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call(client)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"poll_interval": 0}, "poll_interval must be positive"),
        ({"wait_timeout": -1}, "wait_timeout must not be negative"),
    ],
)
def test_invalid_client_options(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MailpitClient(URL, **options)


# Server time


def clock(mocked: responses.RequestsMock, *dates: str) -> None:
    """Mailpit's liveness probe, whose Date header reads ``dates`` in turn, then the last."""
    for date in dates:
        mocked.get(f"{URL}livez", headers={"Date": date})


def test_server_time_waits_for_the_next_second_of_mailpits_clock(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    # A message from 11:22:33.300 is older than a call at 11:22:33.700, which reads 11:22:33.
    clock(
        mocked,
        "Wed, 07 Oct 2026 11:22:33 GMT",
        "Wed, 07 Oct 2026 11:22:33 GMT",
        "Wed, 07 Oct 2026 11:22:34 GMT",
    )

    assert client.server_time() == datetime(2026, 10, 7, 11, 22, 34, tzinfo=UTC)
    assert len(mocked.calls) == 3


def test_server_time_without_a_zone_is_utc(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    clock(mocked, "Wed, 07 Oct 2026 11:22:33 -0000", "Wed, 07 Oct 2026 11:22:34 -0000")

    assert client.server_time() == datetime(2026, 10, 7, 11, 22, 34, tzinfo=UTC)


def test_a_clock_that_stands_still_gives_the_next_second(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    clock(mocked, "Wed, 07 Oct 2026 11:22:33 GMT")
    started = time.monotonic()

    assert client.server_time() == datetime(2026, 10, 7, 11, 22, 34, tzinfo=UTC)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("headers", [{}, {"Date": "yesterday"}])
def test_server_time_falls_back_to_the_local_clock(
    mocked: responses.RequestsMock, client: MailpitClient, headers: dict[str, str]
) -> None:
    mocked.get(f"{URL}livez", headers=headers)
    before = datetime.now(UTC)

    server_time = client.server_time()

    assert before <= server_time <= datetime.now(UTC)


def test_failure_table_shows_messages_without_recipients(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    undisclosed = summary("m1", subject="Newsletter") | {"To": [], "Cc": None, "Bcc": None}
    mocked.get(SEARCH, json=page(undisclosed))

    with pytest.raises(MailpitAssertionError, match=r"11:22:33        -   Newsletter"):
        client.assert_no_message(subject="Newsletter")


def test_failure_table_counts_extra_recipients_and_shortens_long_subjects(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    many = summary("m1", to="a@x.test", cc="b@x.test", subject="S" * 80)
    mocked.get(SEARCH, json=page(many))

    with pytest.raises(MailpitAssertionError) as raised:
        client.assert_no_message(tag="x")

    assert str(raised.value).endswith(f"a@x.test (+1)  {'S' * 57}...")
