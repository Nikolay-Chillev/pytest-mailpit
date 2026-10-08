# pytest-mailpit

[![CI](https://github.com/Nikolay-Chillev/pytest-mailpit/actions/workflows/ci.yml/badge.svg)](https://github.com/Nikolay-Chillev/pytest-mailpit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-mailpit)](https://pypi.org/project/pytest-mailpit/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-mailpit)](https://pypi.org/project/pytest-mailpit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/Nikolay-Chillev/pytest-mailpit/blob/main/LICENSE)

pytest fixtures and a typed client for testing real emails with [Mailpit](https://mailpit.axllent.org) — parallel-safe, no sleeps.

```python
def test_password_reset(page, mailpit_inbox):
    page.goto("http://localhost:8000/forgot-password")
    page.fill("#email", mailpit_inbox.address)
    page.click("text=Send reset link")

    message = mailpit_inbox.wait_for_message(subject="Reset your password")

    page.goto(message.link("/reset/"))
    page.fill("#password", "a new password")
```

> **Status: alpha.** The API may still change before 1.0. Feedback is very welcome in [issues](https://github.com/Nikolay-Chillev/pytest-mailpit/issues) and [discussions](https://github.com/Nikolay-Chillev/pytest-mailpit/discussions).

## Why

Mailpit catches the emails your application sends in development and CI. Testing them from pytest usually means writing the same glue in every project's `conftest.py`: read Mailpit's URL from an environment variable, clear the mailbox, poll in a loop until the email arrives, and pull the link or code out with a regular expression. Clearing the shared mailbox also breaks parallel runs with pytest-xdist.

pytest-mailpit replaces that glue:

- **A unique address for every test.** Tests never see each other's messages, in parallel too, and after a test only its own messages are deleted.
- **Waiting instead of sleeping.** Wait for one message, for several, or check that none arrives, with a timeout. Addresses match exactly: Mailpit's search matches substrings, so `a@example.com` would also find `ba@example.com`.
- **Links and codes.** `message.link("/reset/")` and `message.code()` instead of regular expressions, with HTML entities decoded and dates, prices and phone numbers not mistaken for codes.
- **Failures that explain themselves.** A failure says what was expected and what arrived instead, and points at your test, not at the plugin:

  ```
  >       mailpit_inbox.wait_for_message(subject="Reset your password")
  E       pytest_mailpit.errors.MailpitAssertionError: Expected 1 message matching addressed:"pytest-3f9a2c-7b1e4d9a@example.com" subject:"Reset your password" within 10s, none arrived.
  E       Messages to pytest-3f9a2c-7b1e4d9a@example.com (1):
  E         Received (UTC)  To                                  Subject
  E         09:14:03        pytest-3f9a2c-7b1e4d9a@example.com  Welcome to the shop
  ```
- **Small and typed.** Besides pytest it needs only requests, and it ships type hints.

## Installation

```bash
pip install pytest-mailpit
```

Start Mailpit, for example with Docker:

```bash
docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
```

Point your application's SMTP settings at Mailpit (port 1025 above). pytest-mailpit talks to Mailpit's web UI and API at `http://localhost:8025` unless you [configure](#settings) another URL. The plugin registers itself: there is nothing to add to `conftest.py`.

## Usage

### The inbox

`mailpit_inbox` is an address only this test uses, such as `pytest-3f9a2c-7b1e4d9a@example.com`: the `3f9a2c` part is the same for every run of the test, so its messages are easy to spot in Mailpit's web UI. The address uses only lowercase letters, digits and hyphens, because applications often reject anything else, a `+` included.

```python
def test_sign_up_sends_a_confirmation_code(app_client, mailpit_inbox):
    app_client.post("/sign-up", data={"email": mailpit_inbox.address})

    message = mailpit_inbox.wait_for_message(subject="Confirm your email")

    assert message.sender.address == "no-reply@shop.example.com"
    app_client.post("/confirm", data={"code": message.code()})
```

| Method | What it does |
|---|---|
| `wait_for_message(subject=None, sender=None, query=None, timeout=None)` | Waits until exactly one matching message has arrived and returns it. Fails if none arrives in time, or if more than one matches. |
| `wait_for_messages(count, ...)` | Waits for exactly `count` matching messages and returns them, oldest first. |
| `assert_no_message(subject=None, sender=None, query=None, within=2.0)` | Fails if a matching message arrives within `within` seconds. |
| `messages()` | The messages sent to the address so far, oldest first. |
| `clear()` | Deletes the messages sent to the address. |

`subject` matches any part of the subject, `sender` the whole From address, and `query` adds a [Mailpit search](https://mailpit.axllent.org/docs/usage/search-filters/). The address can be in To, Cc or Bcc.

### Messages

A `Message` has the parsed email: `subject`, `sender`, `to`, `cc`, `bcc`, `reply_to`, `date`, `text`, `html`, `attachments`, `inline`, `tags`, `list_unsubscribe` and more.

```python
message.links()  # every http(s) link, from the HTML and the text part
message.links("/orders/")  # links whose URL contains "/orders/"
message.link(text="Reset password")  # the one link with this visible text
message.link(pattern=r"/reset/\w+$")  # the one link matching a regular expression

message.codes()  # one-time codes, the most likely first
message.code()  # the one code
message.code(r"[A-Z]{2}-\d{4}")  # a code in your own format
```

`link()` and `code()` fail the test unless exactly one candidate is found, and list what the message does contain. Codes are 4–8 digits (or `123 456`) near words such as "code", "OTP" or "verification"; Bulgarian ("код") is understood too.

Attachments are listed with their name, type and size; their content comes from the client:

```python
[invoice] = message.attachments
assert invoice.file_name == "invoice-1001.pdf"
assert mailpit.get_part(message.id, invoice.part_id).startswith(b"%PDF")
```

### More than one address

`mailpit_inbox_factory` creates another inbox each time it is called:

```python
def test_invitation(app_client, mailpit_inbox, mailpit_inbox_factory):
    guest = mailpit_inbox_factory()
    app_client.post("/invite", data={"email": guest.address})

    invitation = guest.wait_for_message(subject="You are invited")
    mailpit_inbox.assert_no_message()
```

### The client

The `mailpit` fixture is a `MailpitClient` for the configured server, shared by the whole session. It also works on its own, outside pytest:

```python
from pytest_mailpit import MailpitClient, build_query

with MailpitClient("http://localhost:8025/") as mailpit:
    for summary in mailpit.search_all(build_query(to="orders@example.com", subject="Invoice")):
        print(summary.created, summary.subject)

    message = mailpit.wait_for_message(recipient="orders@example.com", subject="Invoice")
    source = mailpit.get_raw(message.id)  # the .eml
```

It covers searching, reading whole messages, headers, the raw source and parts, deleting by IDs or by search, read status and waiting. An empty list of IDs never reaches Mailpit, which would otherwise delete or change every message.

### Settings

Command line options win over environment variables, which win over ini settings.

| Setting | Option | Environment | ini (`pytest.ini`, `[tool.pytest.ini_options]`) | Default |
|---|---|---|---|---|
| Mailpit's URL, with its web root if it has one | `--mailpit-url` | `MAILPIT_URL` | `mailpit_url` | `http://localhost:8025/` |
| Username and password (`--ui-auth`) | | `MAILPIT_USERNAME`, `MAILPIT_PASSWORD` | | none |
| TLS verification: `true`, `false` or a CA file | | `MAILPIT_VERIFY` | `mailpit_verify` | `true` |
| How long to wait for a message, in seconds | `--mailpit-timeout` | `MAILPIT_WAIT_TIMEOUT` | `mailpit_wait_timeout` | `10` |
| How often to check, in seconds | | | `mailpit_poll_interval` | `0.5` |
| Domain of the inbox addresses | | | `mailpit_domain` | `example.com` |
| Keep a failed test's messages | | | `mailpit_keep_on_failure` | `true` |
| When Mailpit cannot be reached: `fail` or `skip` | | | `mailpit_unreachable` | `fail` |

The password is read from the environment only, so it stays out of files under version control. `example.com` is reserved for examples, so nothing ever reaches a real person, and unlike `.test` it passes the email validation of most applications.

```ini
[pytest]
mailpit_url = http://mailpit:8025/
mailpit_wait_timeout = 15
```

A single slow test can wait longer:

```python
@pytest.mark.mailpit(timeout=60)
def test_monthly_report(mailpit_inbox): ...
```

### Parallel tests

With pytest-xdist, `pytest -n auto` needs nothing extra. Every address includes the worker (`pytest-gw3-...`), waiting matches it exactly, and cleanup deletes only that test's messages, so workers sharing one Mailpit never interfere.

### When a test fails

The failed test's messages stay in Mailpit (`mailpit_keep_on_failure`), and its report lists them:

```
----------- Mailpit messages to pytest-3f9a2c-7b1e4d9a@example.com ------------
Messages to pytest-3f9a2c-7b1e4d9a@example.com (1):
  Received (UTC)  To                                  Subject
  09:14:03        pytest-3f9a2c-7b1e4d9a@example.com  Welcome to the shop
Mailpit: http://localhost:8025/
```

If Mailpit is not running, the tests that need it say what to do instead of showing a stack of connection errors:

```
Cannot reach Mailpit at http://localhost:8025/ ([Errno 111] Connection refused).
Start Mailpit, for example: docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
or point pytest-mailpit at it with --mailpit-url or MAILPIT_URL.
```

### GitHub Actions

Run Mailpit as a service container next to your tests:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mailpit:
        image: axllent/mailpit
        ports:
          - 8025:8025
          - 1025:1025
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install -e . pytest-mailpit
      # Your application sends email to localhost:1025.
      - run: pytest
```

## Is this the right tool?

| Your test | Use |
|---|---|
| The code under test sends email from the test process | Your framework's outbox, e.g. pytest-django's `mailoutbox` |
| The email leaves the test process: background workers, Docker, a backend in another language, staging, end-to-end tests with Playwright | **Mailpit + pytest-mailpit** |
| You need real external inboxes or deliverability tests | A hosted service such as Mailosaur or Mailtrap |

## Compatibility

Python 3.11–3.14 and pytest 8.4 or newer, on Linux, macOS and Windows. Mailpit 1.22 or newer: CI runs against v1.22.3 and the latest release.

## Contributing

Issues and pull requests are welcome. To work on the code:

```bash
pip install -e . --group dev
pytest
```

The integration tests need a running Mailpit:

```bash
docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit
pytest -m integration
```

## License

[MIT](https://github.com/Nikolay-Chillev/pytest-mailpit/blob/main/LICENSE)
