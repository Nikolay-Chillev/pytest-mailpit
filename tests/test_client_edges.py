"""Edges of the client: queries Mailpit would read differently, credentials, errors, failures."""

import base64
import copy
import pickle
import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import responses
from responses import matchers

from pytest_mailpit import (
    ChaosTriggers,
    MailpitAPIError,
    MailpitAssertionError,
    MailpitClient,
    build_query,
)
from pytest_mailpit._report import message_table
from pytest_mailpit.client import _Criteria
from pytest_mailpit.models import MessageSummary
from pytest_mailpit.search import narrows
from tests.test_waiting import page, summary

URL = "http://mailpit.test:8025/"
SEARCH = re.compile(re.escape(f"{URL}api/v1/search") + r"\?.*")


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as mock:
        yield mock


# Queries whose terms Mailpit drops


@pytest.mark.parametrize(
    "query",
    ["to:", 'tag:""', 'subject:""', "from: ", "after:soon", "larger:big", "()", "<> !", "-to:"],
)
def test_a_query_mailpit_would_drop_entirely_deletes_nothing(query: str) -> None:
    assert not narrows(query)

    with pytest.raises(ValueError, match=r"would ignore every term .* and delete every message"):
        MailpitClient(URL).delete_search(query)


@pytest.mark.parametrize(
    "query",
    [
        'to:"a@example.test"',
        "is:read",
        "HAS:ATTACHMENT",
        "after:2026-10-01",
        "larger:1M",
        '"hello world"',
        "-tag:x",
        'to: subject:"Reset"',
        "код",
    ],
)
def test_a_query_with_something_to_search_for_narrows(query: str) -> None:
    assert narrows(query)


def test_a_narrowing_query_is_deleted(mocked: responses.RequestsMock) -> None:
    mocked.delete(SEARCH, body="ok", match=[matchers.query_param_matcher({"query": "tag:old"})])

    MailpitClient(URL).delete_search("tag:old")


@pytest.mark.parametrize("text", ["from: the shop", "To: all staff", "is:read", " has:inline "])
def test_text_that_mailpit_would_read_as_a_filter_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match=r"would read the text term .* as a filter"):
        build_query(text)


# Credentials and settings


def test_credentials_go_as_utf_8(mocked: responses.RequestsMock) -> None:
    expected = "Basic " + base64.b64encode("qa:парола".encode()).decode()
    mocked.get(
        f"{URL}api/v1/messages",
        json=page(),
        match=[matchers.header_matcher({"Authorization": expected})],
    )

    MailpitClient(URL, username="qa", password="парола").messages()


@pytest.mark.parametrize("timeout", [0, -1])
def test_the_http_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        MailpitClient(URL, timeout=timeout)


def test_search_all_needs_pages_of_at_least_one(mocked: responses.RequestsMock) -> None:
    with pytest.raises(ValueError, match="page_size must be positive"):
        MailpitClient(URL).search_all("tag:x", page_size=0)


# Errors and answers


def test_an_api_error_survives_pickle_and_copy() -> None:
    error = MailpitAPIError("GET", f"{URL}api/v1/info", 503, "starting")

    for again in (pickle.loads(pickle.dumps(error)), copy.copy(error)):
        assert (again.method, again.url, again.status_code, again.detail) == (
            "GET",
            f"{URL}api/v1/info",
            503,
            "starting",
        )
        assert str(again) == str(error)


def test_set_chaos_explains_an_answer_that_is_not_mailpit(mocked: responses.RequestsMock) -> None:
    mocked.put(f"{URL}api/v1/chaos", body="<html>Sign in</html>", content_type="text/html")

    with pytest.raises(MailpitAPIError, match="expected JSON, got text/html"):
        MailpitClient(URL).set_chaos(ChaosTriggers())


def test_header_names_are_case_insensitive(mocked: responses.RequestsMock) -> None:
    # Mailpit spells header names the way Go does.
    mocked.get(f"{URL}api/v1/message/m1/headers", json={"Message-Id": ["<1@shop.test>"]})

    headers = MailpitClient(URL).get_headers("m1")

    assert headers["Message-ID"] == headers["message-id"] == ["<1@shop.test>"]


# Failures


def test_too_many_matches_list_only_the_newest_ten(mocked: responses.RequestsMock) -> None:
    found = [summary(f"m{n}", created=f"2026-10-07T11:00:{n:02}Z") for n in range(12, 0, -1)]
    mocked.get(SEARCH, json=page(*found))

    with pytest.raises(MailpitAssertionError) as failure:
        MailpitClient(URL).assert_no_message(subject="Hello", within=0)

    lines = str(failure.value).splitlines()
    assert lines[0] == (
        'Expected no message matching subject:"Hello", found 12, the newest 10 shown:'
    )
    assert len(lines) == 1 + 1 + 10  # the header, the column titles, ten messages
    assert lines[-1].startswith("  11:00:12")


def test_a_table_spanning_days_shows_the_dates() -> None:
    def summary_from(created: str) -> MessageSummary:
        return MessageSummary.from_api(summary("m", created=created))

    one_day = message_table([summary_from("2026-10-07T11:00:00Z")])
    two_days = message_table(
        [summary_from("2026-10-06T14:30:00Z"), summary_from("2026-10-07T11:00:00Z")]
    )

    assert "  11:00:00  " in one_day
    assert "  2026-10-06 14:30:00  " in two_days
    assert "  2026-10-07 11:00:00  " in two_days


def test_waiting_since_stops_at_the_first_older_page(mocked: responses.RequestsMock) -> None:
    # Newest first: the second page holds only messages from before since.
    newest = page(
        summary("new", created="2026-10-07T12:00:00Z"),
        summary("old", created="2026-10-07T09:00:00Z"),
    )
    newest["messages_count"] = 500
    mocked.get(SEARCH, json=newest)
    since = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    criteria = _Criteria.build(None, None, None, "Hello", None, since)

    [message] = MailpitClient(URL)._matching(criteria)

    assert message.id == "new"
    assert len(mocked.calls) == 1
