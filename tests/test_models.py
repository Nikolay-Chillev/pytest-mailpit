import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from pytest_mailpit import (
    Address,
    Attachment,
    ListUnsubscribe,
    Message,
    MessageList,
    MessageSummary,
    ServerInfo,
)
from tests import samples


def test_message_summary_parses_every_field() -> None:
    summary = MessageSummary.from_api(samples.SUMMARY)

    assert summary == MessageSummary(
        id="Aa1Bb2Cc3Dd4Ee5Ff6Gg7H",
        message_id="order-1001@shop.example.test",
        sender=Address("orders@shop.example.test", "Shop"),
        to=(Address("ivan@example.test", "Ivan Petrov"),),
        cc=(Address("accounts@example.test"),),
        bcc=(),
        reply_to=(Address("support@shop.example.test", "Support"),),
        subject="Поръчка №1001",
        created=datetime(2026, 10, 7, 11, 22, 33, 123456, tzinfo=UTC),
        tags=("orders",),
        size=4821,
        attachments=1,
        snippet="Thank you for your order.",
        read=False,
        username="shop",
    )


def test_fields_missing_on_older_servers_get_defaults_and_unknown_fields_are_ignored() -> None:
    summary = MessageSummary.from_api(samples.OLD_SUMMARY)

    assert (summary.username, summary.reply_to, summary.snippet) == ("", (), "")


def test_null_lists_become_empty_tuples() -> None:
    data = samples.SUMMARY | {"To": None, "Cc": None, "Tags": None}

    summary = MessageSummary.from_api(data)

    assert (summary.to, summary.cc, summary.tags) == ((), (), ())


def test_message_parses_bodies_attachments_and_list_unsubscribe() -> None:
    message = Message.from_api(samples.MESSAGE)

    assert message.subject == "Поръчка №1001"
    assert message.bcc == ()
    assert message.return_path == "bounces@shop.example.test"
    assert message.date == datetime(2026, 10, 7, 14, 22, 33, tzinfo=timezone(timedelta(hours=3)))
    assert "https://shop.example.test/orders/1001" in message.text
    assert message.html.startswith("<p>")
    assert message.attachments == (
        Attachment(
            part_id="2",
            file_name="invoice-1001.pdf",
            content_type="application/pdf",
            size=1234,
            checksums={"MD5": "0123456789abcdef0123456789abcdef"},
        ),
    )
    assert message.inline == ()
    assert message.list_unsubscribe == ListUnsubscribe(
        header="<mailto:unsubscribe@shop.example.test>, <https://shop.example.test/u/1>",
        header_post="List-Unsubscribe=One-Click",
        links=("unsubscribe@shop.example.test", "https://shop.example.test/u/1"),
    )


def test_message_without_list_unsubscribe_gets_an_empty_one() -> None:
    data = {key: value for key, value in samples.MESSAGE.items() if key != "ListUnsubscribe"}

    assert Message.from_api(data).list_unsubscribe == ListUnsubscribe()


def test_message_list_parses_counts_and_messages() -> None:
    page = MessageList.from_api(samples.MESSAGE_LIST)

    assert (page.total, page.unread, page.messages_count, page.messages_unread) == (12, 3, 1, 1)
    assert [summary.id for summary in page.messages] == ["Aa1Bb2Cc3Dd4Ee5Ff6Gg7H"]
    assert page.tags == ("orders",)


def test_empty_message_list() -> None:
    page = MessageList.from_api({"total": 0, "messages_count": 0, "messages": None})

    assert (page.messages, page.messages_count) == ((), 0)


def test_server_info() -> None:
    info = ServerInfo.from_api(samples.INFO)

    assert (info.version, info.messages, info.unread) == ("v1.31.4", 12, 3)
    assert info.tags == {"orders": 1}


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (Address("ivan@example.test", "Ivan Petrov"), "Ivan Petrov <ivan@example.test>"),
        (Address("ivan@example.test"), "ivan@example.test"),
    ],
)
def test_address_str(address: Address, expected: str) -> None:
    assert str(address) == expected


def test_models_are_read_only() -> None:
    summary = MessageSummary.from_api(samples.SUMMARY)

    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.subject = "changed"  # type: ignore[misc]
