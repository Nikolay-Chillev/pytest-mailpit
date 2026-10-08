# pytest-mailpit with Flask

A tiny Flask application that emails a password reset link with [Flask-Mail](https://flask-mail.readthedocs.io/), and tests that follow the link as the user would. CI runs this example on every change.

```bash
docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
pip install pytest-mailpit flask flask-mail
pytest
```

## How it fits together

- [`shop.py`](shop.py) is an application factory: `create_app(config)` takes settings, as most Flask applications do.
- The `client` fixture in [`tests/test_password_reset.py`](tests/test_password_reset.py) creates the application with `MAIL_SERVER` and `MAIL_PORT` from `mailpit_smtp` (`MAILPIT_SMTP`, default `localhost:1025`; with `mailpit_container = true`, the container's SMTP port).
- Flask-Mail sends nothing while `TESTING` is on: `MAIL_SUPPRESS_SEND` follows it. The fixture sets `MAIL_SUPPRESS_SEND = False`, or no email would ever reach Mailpit.
- The test reads the email with `mailpit_inbox`, finds the link by its text and opens it with Flask's test client, which takes the link's full URL.

The same works with any other email library: point its SMTP host and port at `mailpit_smtp` in the fixture that creates the application.
