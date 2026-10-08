"""The login code email as the user gets it: sent in a background task, read from Mailpit."""

import pytest
from fastapi.testclient import TestClient
from shop import SMTPSettings, app, smtp_settings


@pytest.fixture
def client(mailpit_smtp):
    app.dependency_overrides[smtp_settings] = lambda: SMTPSettings(*mailpit_smtp)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_login_with_the_emailed_code(client, mailpit_inbox):
    client.post("/login/code", json={"email": mailpit_inbox.address})

    code = mailpit_inbox.wait_for_message(subject="Your login code").code()
    response = client.post("/login", json={"email": mailpit_inbox.address, "code": code})

    assert response.json() == {"detail": f"Logged in as {mailpit_inbox.address}"}


def test_a_code_works_once(client, mailpit_inbox):
    client.post("/login/code", json={"email": mailpit_inbox.address})
    code = mailpit_inbox.wait_for_message().code()
    login = {"email": mailpit_inbox.address, "code": code}

    assert client.post("/login", json=login).status_code == 200
    assert client.post("/login", json=login).status_code == 401
