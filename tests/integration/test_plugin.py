"""The plugin end to end: inner pytest sessions that send real email to a real Mailpit."""

import uuid

import pytest

from pytest_mailpit import MailpitClient, build_query

pytestmark = pytest.mark.integration

# The inner session's conftest: send an email over SMTP to Mailpit.
CONFTEST = """
import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urlsplit

import pytest


@pytest.fixture
def send():
    smtp = urlsplit("//" + os.environ.get("MAILPIT_SMTP", "localhost:1025"))

    def send(to, subject, text="Hello"):
        message = EmailMessage()
        message["From"] = "app@example.test"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        with smtplib.SMTP(smtp.hostname, smtp.port, timeout=10) as server:
            server.send_message(message)

    return send
"""


@pytest.fixture
def domain(pytester: pytest.Pytester, mailpit_url: str) -> str:
    """A domain only this test's inner session uses, so its messages can be counted."""
    domain = f"{uuid.uuid4().hex[:12]}.example.com"
    pytester.makeini(f"[pytest]\nmailpit_url = {mailpit_url}\nmailpit_domain = {domain}\n")
    pytester.makeconftest(CONFTEST)
    return domain


def messages_to(client: MailpitClient, domain: str) -> list[str]:
    return [summary.subject for summary in client.search_all(build_query(addressed=domain))]


def test_a_password_reset_end_to_end(
    pytester: pytest.Pytester, client: MailpitClient, domain: str
) -> None:
    pytester.makepyfile(
        """
        def test_reset(mailpit_inbox, send):
            send(
                mailpit_inbox.address,
                "Reset your password",
                "Your code is 482913. Or open https://shop.test/reset?token=abc",
            )

            message = mailpit_inbox.wait_for_message(subject="Reset")

            assert message.code() == "482913"
            assert message.link("/reset") == "https://shop.test/reset?token=abc"
            mailpit_inbox.assert_no_message(subject="Welcome", within=0.5)
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)

    assert messages_to(client, domain) == []


def test_parallel_tests_never_see_each_others_messages(
    pytester: pytest.Pytester, client: MailpitClient, domain: str
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize("case", range(8))
        def test_signup(mailpit_inbox, send, case):
            send(mailpit_inbox.address, f"Welcome, user {case}")

            [message] = mailpit_inbox.wait_for_messages(1)

            assert message.subject == f"Welcome, user {case}"
            assert "-gw" in mailpit_inbox.address
        """
    )

    pytester.runpytest("-n", "4").assert_outcomes(passed=8)

    assert messages_to(client, domain) == []


def test_a_failed_test_keeps_its_messages_and_shows_them(
    pytester: pytest.Pytester, client: MailpitClient, domain: str
) -> None:
    pytester.makepyfile(
        """
        def test_wrong_email(mailpit_inbox, send):
            send(mailpit_inbox.address, "Welcome")

            mailpit_inbox.wait_for_message(subject="Reset your password", timeout=1)
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*Expected 1 message matching addressed:*subject:*Reset your password* within 1s*",
            f"*Messages to pytest-*@{domain} (1):",
            "*Mailpit messages to pytest-*",
        ]
    )
    assert messages_to(client, domain) == ["Welcome"]
