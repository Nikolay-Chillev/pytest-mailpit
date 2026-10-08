"""The sign-up email as the customer gets it: through Django's SMTP backend and Mailpit."""

import pytest

# Every test of this module sends Django's email to Mailpit.
pytestmark = pytest.mark.usefixtures("mailpit_django")


def test_sign_up_emails_a_confirmation_link(client, mailpit_inbox):
    response = client.post("/sign-up/", {"email": mailpit_inbox.address})
    assert response.status_code == 200

    message = mailpit_inbox.wait_for_message(subject="Confirm your email")
    confirmed = client.get(message.link(text="Confirm your email"))

    assert confirmed.content.decode() == f"{mailpit_inbox.address} is confirmed."


def test_the_email_comes_from_the_shop_with_a_text_part(client, mailpit_inbox):
    client.post("/sign-up/", {"email": mailpit_inbox.address})

    message = mailpit_inbox.wait_for_message()

    assert message.sender.address == "shop@example.com"
    assert message.text.startswith("Welcome to the shop!")


def test_a_changed_link_is_refused(client, mailpit_inbox):
    client.post("/sign-up/", {"email": mailpit_inbox.address})
    link = mailpit_inbox.wait_for_message().link(text="Confirm your email")

    response = client.get(link.replace("/confirm/", "/confirm/x"))

    assert response.status_code == 400
