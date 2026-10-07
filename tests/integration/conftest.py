import os
import smtplib
import time
import uuid
from collections.abc import Callable, Iterator
from email.message import EmailMessage
from urllib.parse import urlsplit

import pytest

from pytest_mailpit import MailpitClient, MessageSummary


@pytest.fixture(scope="session")
def mailpit_url() -> str:
    url = os.environ.get("MAILPIT_URL", "http://localhost:8025/")
    return url if url.endswith("/") else f"{url}/"


@pytest.fixture(scope="session")
def smtp_address() -> tuple[str, int]:
    """Host and port of Mailpit's SMTP server, from ``MAILPIT_SMTP`` (``host:port``)."""
    parts = urlsplit(f"//{os.environ.get('MAILPIT_SMTP', 'localhost:1025')}")
    return parts.hostname or "localhost", parts.port or 1025


@pytest.fixture
def client(mailpit_url: str) -> Iterator[MailpitClient]:
    with MailpitClient(mailpit_url) as client:
        yield client


@pytest.fixture
def recipient() -> str:
    """An address no other test uses, so tests can share one Mailpit."""
    return f"it-{uuid.uuid4().hex[:16]}@example.test"


SendEmail = Callable[..., EmailMessage]


@pytest.fixture
def send_email(smtp_address: tuple[str, int]) -> SendEmail:
    """Send an email to Mailpit over SMTP and return it."""

    def send(
        to: str,
        *,
        subject: str = "Hello",
        text: str = "Hello from the pytest-mailpit test suite.",
        html: str | None = None,
        cc: str | None = None,
        attachment: tuple[str, bytes] | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = "Test Sender <sender@example.test>"
        message["To"] = to
        if cc:
            message["Cc"] = cc
        message["Subject"] = subject
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        if attachment:
            file_name, content = attachment
            message.add_attachment(
                content, maintype="application", subtype="octet-stream", filename=file_name
            )
        with smtplib.SMTP(*smtp_address, timeout=10) as smtp:
            smtp.send_message(message)
        return message

    return send


def wait_for_search(
    client: MailpitClient, query: str, *, count: int = 1, timeout: float = 10
) -> list[MessageSummary]:
    """Poll until ``query`` finds ``count`` messages. A stand-in until the client can wait."""
    deadline = time.monotonic() + timeout
    while True:
        found = client.search_all(query)
        if len(found) >= count or time.monotonic() >= deadline:
            assert len(found) == count, f"expected {count} messages for {query}, found {len(found)}"
            return found
        time.sleep(0.2)
