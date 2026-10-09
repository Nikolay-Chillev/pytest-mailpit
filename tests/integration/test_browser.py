"""Opening real emails in a real browser (Chromium, through Playwright)."""

import base64
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

from pytest_mailpit import MailpitClient
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration

# A 1x1 PNG, so the browser has an image to decode.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def page() -> Iterator["Page"]:
    # Imported here, so that collecting the tests needs no Playwright.
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser.new_page()
        finally:
            browser.close()


def test_open_the_email_and_click_its_button(
    client: MailpitClient, send_email: SendEmail, recipient: str, page: "Page", mailpit_url: str
) -> None:
    confirm = f"{mailpit_url}livez"
    send_email(
        recipient,
        subject="Welcome",
        html=(
            '<h1>Welcome to the shop!</h1><img src="cid:logo" alt="Logo">'
            f'<p><a href="{confirm}">Confirm your email</a></p>'
        ),
        inline_image=PNG,
    )
    message = client.wait_for_message(recipient=recipient)

    message.open(page)

    assert page.get_by_role("heading").inner_text() == "Welcome to the shop!"
    # Mailpit links the inline image to its API, so the browser can load it.
    assert page.locator("img").evaluate("image => image.naturalWidth") == 1
    page.get_by_role("link", name="Confirm your email").click()
    page.wait_for_url(confirm)


def test_screenshot_of_the_email(
    client: MailpitClient, send_email: SendEmail, recipient: str, page: "Page"
) -> None:
    send_email(recipient, html="<h1>Your order has shipped</h1>")
    message = client.wait_for_message(recipient=recipient)

    png = message.screenshot(page)

    assert png.startswith(b"\x89PNG")
