import os

import requests

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")


def test_sign_up_sends_a_confirmation_link(mailpit_inbox):
    response = requests.post(
        f"{APP_URL}/sign-up", data={"email": mailpit_inbox.address}, timeout=10
    )
    assert response.status_code == 201

    message = mailpit_inbox.wait_for_message(subject="Confirm your email")

    assert message.sender.address == "no-reply@shop.example.com"
    assert message.link(text="Confirm your email").startswith(f"{APP_URL}/confirm?token=")


def test_unknown_pages_send_nothing(mailpit_inbox):
    requests.post(f"{APP_URL}/nothing-here", data={"email": mailpit_inbox.address}, timeout=10)

    mailpit_inbox.assert_no_message(within=1)
