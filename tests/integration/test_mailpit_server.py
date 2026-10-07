"""Checks that the test environment works: a real Mailpit receives mail and answers the API."""

import smtplib
import time
import uuid
from email.message import EmailMessage
from urllib.parse import urljoin

import pytest
import requests

pytestmark = pytest.mark.integration


def test_server_reports_its_version(mailpit_url: str) -> None:
    response = requests.get(urljoin(mailpit_url, "api/v1/info"), timeout=10)

    assert response.status_code == 200
    assert response.json()["Version"]


def test_email_sent_over_smtp_is_found_through_the_api(
    mailpit_url: str, smtp_address: tuple[str, int]
) -> None:
    recipient = f"smoke-{uuid.uuid4().hex[:12]}@example.test"
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = recipient
    message["Subject"] = "Smoke test"
    message.set_content("Hello from the pytest-mailpit test suite.")

    with smtplib.SMTP(*smtp_address, timeout=10) as smtp:
        smtp.send_message(message)

    deadline = time.monotonic() + 10
    while True:
        response = requests.get(
            urljoin(mailpit_url, "api/v1/search"), params={"query": f'to:"{recipient}"'}, timeout=10
        )
        response.raise_for_status()
        messages = response.json()["messages"]
        if messages or time.monotonic() >= deadline:
            break
        time.sleep(0.2)

    assert [m["Subject"] for m in messages] == ["Smoke test"]
