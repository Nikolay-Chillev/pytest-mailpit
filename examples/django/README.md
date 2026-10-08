# pytest-mailpit with Django

A tiny Django project that emails a confirmation link at sign-up, and tests that follow the link as the customer would. CI runs this example with Django 5.2 and 6.1 on every change.

```bash
docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
pip install pytest-mailpit pytest-django django
pytest
```

## How it fits together

- Django's test runner, and pytest-django, keep sent email in memory, in `django.core.mail.outbox`. The `mailpit_django` fixture sends the test's email over SMTP to Mailpit instead, so the test reads it with `mailpit_inbox` as the customer gets it: the MIME parts, the headers and the HTML, with Mailpit's link and HTML checks and the browser helpers.
- [`tests/test_sign_up.py`](tests/test_sign_up.py) uses it for every test of the module, with `pytestmark = pytest.mark.usefixtures("mailpit_django")`.
- On Django 6.1 and newer, every mailer in `MAILERS` goes to Mailpit; on older versions, `EMAIL_BACKEND`, `EMAIL_HOST` and `EMAIL_PORT` point at it. Login and TLS are off, since Mailpit needs neither. After the test, Django's settings are back as they were.
- `mailpit_smtp` (`MAILPIT_SMTP`, default `localhost:1025`) is where the email goes; with `mailpit_container = true` it is the container's SMTP port.

For the whole test suite, add an autouse fixture to `conftest.py`:

```python
import pytest


@pytest.fixture(autouse=True)
def email_to_mailpit(mailpit_django):
    pass
```

## Email from another process

`mail.outbox` only sees email sent in the test's process. A Celery worker, or the application running in a container, sends email through its own settings: point them at Mailpit's SMTP server, and the same `mailpit_inbox` test reads that email, without `mailpit_django`.

If a test waits for an email that Django kept in memory, the failure says so and suggests `mailpit_django`.
