"""Attachments and List-Unsubscribe of real emails, as a real Mailpit parses them."""

import hashlib

import pytest

from pytest_mailpit import MailpitAssertionError, MailpitClient
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n" + b"0123456789" * 200
PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64


def test_attachment_and_its_content(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Your invoice",
        html='<p>Thank you!</p><img src="cid:logo">',
        attachment=("invoice-1001.pdf", PDF),
        inline_image=PNG,
    )
    message = client.wait_for_message(recipient=recipient)

    invoice = message.attachment("invoice-*.pdf", content_type="application/pdf")

    assert invoice.size == len(PDF)
    assert client.get_attachment(invoice) == PDF
    assert (
        hashlib.sha256(client.get_attachment(invoice)).hexdigest()
        == hashlib.sha256(PDF).hexdigest()
    )
    logo = message.attachment(content_type="image/png", include_inline=True)
    assert client.get_attachment(logo) == PNG
    with pytest.raises(MailpitAssertionError, match="found 0"):
        message.attachment(content_type="image/png")


def test_one_click_unsubscribe(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Newsletter",
        headers={
            "List-Unsubscribe": "<mailto:unsubscribe@shop.example.com>, <https://shop.example.com/u/7>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    message = client.wait_for_message(recipient=recipient)

    assert message.unsubscribe_link(one_click=True) == "https://shop.example.com/u/7"
    assert message.list_unsubscribe.mailto_link == "mailto:unsubscribe@shop.example.com"


def test_an_invalid_list_unsubscribe_header_is_reported_with_mailpits_reason(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Newsletter",
        headers={"List-Unsubscribe": "https://shop.example.com/u/7"},
    )
    message = client.wait_for_message(recipient=recipient)

    with pytest.raises(
        MailpitAssertionError, match=r"has an invalid List-Unsubscribe header: .*<>"
    ):
        message.unsubscribe_link()


def test_a_message_without_list_unsubscribe(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient, subject="Receipt")
    message = client.wait_for_message(recipient=recipient)

    with pytest.raises(MailpitAssertionError, match="has no List-Unsubscribe header"):
        message.unsubscribe_link()
