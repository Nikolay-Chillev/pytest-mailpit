import os
import smtplib
import uuid
from collections.abc import Callable, Iterator
from email.message import EmailMessage
from urllib.parse import urlsplit

import pytest

from pytest_mailpit import MailpitClient, MessageSummary, build_query


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
        bcc: str | None = None,
        attachment: tuple[str, bytes] | None = None,
        inline_image: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = "Test Sender <sender@example.test>"
        message["To"] = to
        if cc:
            message["Cc"] = cc
        if bcc:
            # smtplib sends Bcc recipients in the envelope and drops the header.
            message["Bcc"] = bcc
        message["Subject"] = subject
        for name, value in (headers or {}).items():
            message[name] = value
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        if inline_image:
            # An image the HTML shows with <img src="cid:logo">.
            html_part = message.get_body(preferencelist=("html",))
            assert html_part is not None, "an inline image needs an HTML part"
            html_part.add_related(inline_image, maintype="image", subtype="png", cid="<logo>")
        if attachment:
            file_name, content = attachment
            maintype, subtype = (
                ("application", "pdf")
                if file_name.endswith(".pdf")
                else ("application", "octet-stream")
            )
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=file_name)
        with smtplib.SMTP(*smtp_address, timeout=10) as smtp:
            smtp.send_message(message)
        return message

    return send


def arrived(client: MailpitClient, recipient: str, *, count: int = 1) -> list[MessageSummary]:
    """Wait for ``count`` messages to ``recipient`` and return their summaries, newest first.

    Waiting fetches the messages, so Mailpit has marked them as read.
    """
    client.wait_for_messages(count, recipient=recipient)
    return client.search_all(build_query(to=recipient))
