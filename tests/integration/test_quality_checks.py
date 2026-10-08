"""Mailpit's link and HTML checks of real emails.

The links point at Mailpit itself, so the server must be allowed to request
internal addresses (MP_ALLOW_INTERNAL_HTTP_REQUESTS=true on Mailpit 1.29.2+).
"""

import pytest

from pytest_mailpit import MailpitAssertionError, MailpitClient
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration

# Seen from inside the Mailpit container.
WORKING = "http://localhost:8025/livez"
MISSING = "http://localhost:8025/api/v1/message/this-message-does-not-exist"


def test_links_that_work_pass(client: MailpitClient, send_email: SendEmail, recipient: str) -> None:
    send_email(recipient, html=f'<a href="{WORKING}">Health</a>')
    message = client.wait_for_message(recipient=recipient)

    result = message.assert_links_work()

    assert [(link.url, link.status_code) for link in result.links] == [(WORKING, 200)]


def test_a_broken_link_fails_with_its_status(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Your order",
        html=f'<a href="{WORKING}">Health</a> <a href="{MISSING}">Track</a>',
    )
    message = client.wait_for_message(recipient=recipient)

    with pytest.raises(MailpitAssertionError) as raised:
        message.assert_links_work()

    assert str(raised.value).splitlines() == [
        f"1 of 2 links in message 'Your order' to {recipient} are broken:",
        f"  404 Not Found  {MISSING}",
    ]
    assert message.assert_links_work(ignore=["/api/v1/message/"]).errors == 1


def test_html_support(client: MailpitClient, send_email: SendEmail, recipient: str) -> None:
    html = (
        "<html><head><style>.row { display: flex; gap: 8px }</style></head>"
        '<body><div class="row"><p>Thank you for your order.</p></div></body></html>'
    )
    send_email(recipient, subject="Your order", html=html)
    message = client.wait_for_message(recipient=recipient)

    result = message.assert_html_support(at_least=0)

    assert 0 < result.supported < 100
    assert result.warnings
    assert result.warnings[0].url.startswith("https://www.caniemail.com/")
    with pytest.raises(MailpitAssertionError, match=r"expected at least 100%\.\nWorst problems"):
        message.assert_html_support(at_least=100)
