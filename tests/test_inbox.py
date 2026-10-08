import re
from collections.abc import Iterator

import pytest
import responses
from responses import matchers

from pytest_mailpit import Inbox, MailpitClient
from pytest_mailpit.inbox import unique_address
from tests import samples
from tests.test_waiting import SEARCH, URL, page, summary

ADDRESS = "pytest-3f9a2c-7b1e4d9a@example.com"


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def inbox() -> Inbox:
    return Inbox(MailpitClient(URL, poll_interval=0.01), ADDRESS, wait_timeout=0.2)


# Addresses


def test_unique_address_names_the_test_and_is_random() -> None:
    first = unique_address("tests/test_signup.py::test_reset", domain="example.com")
    second = unique_address("tests/test_signup.py::test_reset", domain="example.com")

    assert re.fullmatch(r"pytest-[0-9a-f]{6}-[0-9a-f]{8}@example\.com", first)
    assert first != second
    assert first.split("-")[1] == second.split("-")[1]


def test_unique_address_includes_the_xdist_worker() -> None:
    address = unique_address("t", domain="shop.test", worker="gw12")

    assert re.fullmatch(r"pytest-gw12-[0-9a-f]{6}-[0-9a-f]{8}@shop\.test", address)


def test_unique_address_keeps_only_safe_characters_of_odd_worker_names() -> None:
    address = unique_address("t", domain="example.com", worker="Worker_#1 with a very long name")

    local = address.split("@")[0]
    assert re.fullmatch(r"[a-z0-9-]+", local)
    assert local.split("-")[1] == "worker1withavery"


@pytest.mark.parametrize("domain", ["", "a@b.test", " example.com"])
def test_unique_address_rejects_bad_domains(domain: str) -> None:
    with pytest.raises(ValueError, match="domain"):
        unique_address("t", domain=domain)


# Inbox


def test_inbox_is_its_address(inbox: Inbox) -> None:
    assert str(inbox) == ADDRESS
    assert repr(inbox) == f"Inbox({ADDRESS!r})"


def test_inbox_waits_for_messages_to_its_address(
    mocked: responses.RequestsMock, inbox: Inbox
) -> None:
    query = f'tag:"x" addressed:"{ADDRESS}" from:"shop@x.test" subject:"Reset"'
    mocked.get(
        SEARCH,
        json=page(summary("m1", to=ADDRESS, sender="shop@x.test", subject="Reset")),
        match=[matchers.query_param_matcher({"query": query, "start": 0, "limit": 250})],
    )
    mocked.get(f"{URL}api/v1/message/m1", json=samples.MESSAGE | {"ID": "m1"})

    message = inbox.wait_for_message(subject="Reset", sender="shop@x.test", query='tag:"x"')

    assert message.id == "m1"


def test_inbox_wait_for_messages_and_assert_no_message(
    mocked: responses.RequestsMock, inbox: Inbox
) -> None:
    mocked.get(SEARCH, json=page(summary("m1", to=ADDRESS)))
    mocked.get(f"{URL}api/v1/message/m1", json=samples.MESSAGE | {"ID": "m1"})

    assert [message.id for message in inbox.wait_for_messages(1)] == ["m1"]
    with pytest.raises(AssertionError, match="Expected no message"):
        inbox.assert_no_message(within=0)


def test_inbox_uses_its_own_timeout(mocked: responses.RequestsMock, inbox: Inbox) -> None:
    mocked.get(SEARCH, json=page())
    mocked.get(f"{URL}api/v1/messages", json=page())

    with pytest.raises(AssertionError, match=r"within 0\.2s"):
        inbox.wait_for_message()
    with pytest.raises(AssertionError, match=r"within 0s"):
        inbox.wait_for_messages(2, timeout=0)


def test_messages_are_only_those_to_the_exact_address_oldest_first(
    mocked: responses.RequestsMock, inbox: Inbox
) -> None:
    mocked.get(
        SEARCH,
        json=page(
            summary("new", cc=ADDRESS.upper(), to="x@x.test", created="2026-10-07T11:00:05Z"),
            summary("other", to=f"x{ADDRESS}", created="2026-10-07T11:00:03Z"),
            summary("old", to=ADDRESS, created="2026-10-07T11:00:01Z"),
        ),
    )

    assert [message.id for message in inbox.messages()] == ["old", "new"]


def test_clear_deletes_only_the_inboxs_messages(
    mocked: responses.RequestsMock, inbox: Inbox
) -> None:
    mocked.get(SEARCH, json=page(summary("mine", to=ADDRESS), summary("other", to=f"x{ADDRESS}")))
    mocked.delete(
        f"{URL}api/v1/messages",
        body="ok",
        match=[matchers.json_params_matcher({"IDs": ["mine"]})],
    )

    inbox.clear()

    assert len([call for call in mocked.calls if call.request.method == "DELETE"]) == 1


def test_describe_lists_the_messages_and_links_to_mailpit(
    mocked: responses.RequestsMock, inbox: Inbox
) -> None:
    mocked.get(SEARCH, json=page(summary("m1", to=ADDRESS, subject="Welcome")))

    assert inbox.describe() == (
        f"Messages to {ADDRESS} (1):\n"
        f"  Received (UTC)  {'To':<{len(ADDRESS)}}  Subject\n"
        f"  11:22:33        {ADDRESS}  Welcome\n"
        f"Mailpit: {URL}"
    )


def test_describe_an_empty_inbox(mocked: responses.RequestsMock, inbox: Inbox) -> None:
    mocked.get(SEARCH, json=page())

    assert inbox.describe() == f"No messages to {ADDRESS}.\nMailpit: {URL}"
