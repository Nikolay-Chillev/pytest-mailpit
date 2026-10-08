"""The password reset email as the user gets it: through Flask-Mail and Mailpit."""

import pytest
from shop import create_app


@pytest.fixture
def client(mailpit_smtp):
    app = create_app(
        {
            "TESTING": True,
            # Flask-Mail sends nothing while TESTING is on, unless told to.
            "MAIL_SUPPRESS_SEND": False,
            "MAIL_SERVER": mailpit_smtp.host,
            "MAIL_PORT": mailpit_smtp.port,
        }
    )
    return app.test_client()


def test_the_reset_link_works_once(client, mailpit_inbox):
    client.post("/forgot-password", data={"email": mailpit_inbox.address})

    message = mailpit_inbox.wait_for_message(subject="Reset your password")
    link = message.link(text="Reset your password")

    assert client.get(link).status_code == 200
    assert client.get(link).status_code == 400


def test_the_email_comes_from_the_shop(client, mailpit_inbox):
    client.post("/forgot-password", data={"email": mailpit_inbox.address})

    message = mailpit_inbox.wait_for_message()

    assert message.sender.address == "shop@example.com"
    assert message.text.startswith("Reset your password: http://localhost/reset-password/")
