"""The same login from an async test: httpx2's AsyncClient and mailpit_async_inbox."""

import httpx2
import pytest
from shop import SMTPSettings, app, smtp_settings


@pytest.fixture
def smtp_to_mailpit(mailpit_smtp):
    app.dependency_overrides[smtp_settings] = lambda: SMTPSettings(*mailpit_smtp)
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.usefixtures("smtp_to_mailpit")
async def test_login_with_the_emailed_code(mailpit_async_inbox):
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://shop.test") as client:
        await client.post("/login/code", json={"email": mailpit_async_inbox.address})

        message = await mailpit_async_inbox.wait_for_message(subject="Your login code")
        login = {"email": mailpit_async_inbox.address, "code": message.code()}
        response = await client.post("/login", json=login)

    assert response.json() == {"detail": f"Logged in as {mailpit_async_inbox.address}"}
