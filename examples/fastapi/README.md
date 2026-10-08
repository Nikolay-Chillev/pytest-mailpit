# pytest-mailpit with FastAPI

A tiny FastAPI application that emails a login code in a background task, and tests that log in with the code as the user would. CI runs this example on every change.

```bash
docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
pip install pytest-mailpit fastapi httpx2
pytest
```

## How it fits together

- [`shop.py`](shop.py) gets its SMTP settings from a dependency, `smtp_settings`, and sends the email in a background task.
- The `client` fixture in [`tests/test_login_code.py`](tests/test_login_code.py) overrides that dependency with `mailpit_smtp` (`MAILPIT_SMTP`, default `localhost:1025`; with `mailpit_container = true`, the container's SMTP port), FastAPI's usual way to change settings in tests.
- `TestClient` runs background tasks before it returns the response, and Mailpit receives the email moments later; `mailpit_inbox.wait_for_message()` waits for it, so the test needs no sleeps.
- `message.code()` finds the one-time code in the email.

Starlette's `TestClient` uses [httpx2](https://github.com/pydantic/httpx2), and warns when it has to fall back to httpx.
