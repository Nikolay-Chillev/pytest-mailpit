"""Waiting, link and code extraction against a real Mailpit."""

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from pytest_mailpit import MailpitAssertionError, MailpitClient, build_query
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration


def test_waits_for_a_message_sent_later(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    sender = threading.Timer(0.5, send_email, args=(recipient,), kwargs={"subject": "Late"})
    sender.start()
    try:
        message = client.wait_for_message(recipient=recipient, timeout=10)
    finally:
        sender.join()

    assert message.subject == "Late"


def test_recipient_is_matched_exactly(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    # Mailpit's search finds the recipient inside the longer address as well.
    send_email(f"x{recipient}", subject="For someone else")
    send_email(recipient, subject="For me")
    client.wait_for_messages(2, build_query(addressed=recipient))

    assert client.wait_for_message(recipient=recipient).subject == "For me"


def test_recipient_can_be_in_bcc(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email("someone@example.test", bcc=recipient, subject="Blind copy")

    assert client.wait_for_message(recipient=recipient).subject == "Blind copy"


def test_since_the_server_time(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient, subject="Before")
    client.wait_for_message(recipient=recipient)
    # The server time has a one-second resolution, so step past the first message.
    since = client.server_time() + timedelta(seconds=1)
    time.sleep(1.1)
    send_email(recipient, subject="After")

    assert client.wait_for_message(recipient=recipient, since=since).subject == "After"


def test_server_time_is_close_to_now(client: MailpitClient) -> None:
    assert abs(client.server_time() - datetime.now(UTC)) < timedelta(minutes=5)


def test_timeout_failure_lists_what_arrived(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient, subject="Welcome")
    client.wait_for_message(recipient=recipient)

    with pytest.raises(MailpitAssertionError) as raised:
        client.wait_for_message(recipient=recipient, subject="Reset your password", timeout=0.5)

    assert "none arrived" in str(raised.value)
    assert f"{recipient}  Welcome" in str(raised.value)


def test_assert_no_message(client: MailpitClient, send_email: SendEmail, recipient: str) -> None:
    client.assert_no_message(recipient=recipient, within=0.5)

    send_email(recipient, subject="Unexpected")
    with pytest.raises(MailpitAssertionError, match="Unexpected"):
        client.assert_no_message(recipient=recipient, within=10)


def test_link_and_code_from_a_real_email(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Нулиране на парола",
        text="Вашият код за потвърждение е 482913.\nИли отворете https://shop.test/reset?t=abc&u=1",
        html=(
            "<p>Вашият код за потвърждение е <b>482913</b>.</p>"
            '<p><a href="https://shop.test/reset?t=abc&amp;u=1">Нулирай паролата</a></p>'
        ),
    )

    message = client.wait_for_message(recipient=recipient)

    assert message.link(text="Нулирай") == "https://shop.test/reset?t=abc&u=1"
    assert message.code() == "482913"
