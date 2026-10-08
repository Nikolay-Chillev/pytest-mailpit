"""Async waiting against a real Mailpit: the event loop keeps running while a test waits."""

import asyncio

import pytest

from pytest_mailpit import AsyncInbox, Inbox, MailpitAssertionError
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration


async def send_later(send: SendEmail, to: str) -> None:
    """Stands in for a background task of the application: sends an email a moment later."""
    await asyncio.sleep(0.3)
    send(to, subject="From the event loop")


def test_an_email_sent_from_the_event_loop_arrives_while_waiting(
    mailpit_async_inbox: AsyncInbox, send_email: SendEmail
) -> None:
    async def test() -> str:
        sending = asyncio.create_task(send_later(send_email, mailpit_async_inbox.address))
        message = await mailpit_async_inbox.wait_for_message(subject="From the event loop")
        await sending
        return message.subject

    assert asyncio.run(test()) == "From the event loop"


def test_waiting_with_the_sync_inbox_blocks_the_event_loop(
    mailpit_inbox: Inbox, send_email: SendEmail
) -> None:
    async def test() -> None:
        sending = asyncio.create_task(send_later(send_email, mailpit_inbox.address))
        try:
            # The task cannot run until this returns, so the email is not sent in time.
            mailpit_inbox.wait_for_message(subject="From the event loop", timeout=1.5)
        finally:
            sending.cancel()

    with pytest.raises(MailpitAssertionError, match="none arrived"):
        asyncio.run(test())
