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
- **Failures that explain themselves.** A failure says what was expected and what arrived instead, and points at your test, not at the plugin. The failed test's emails are attached to Allure and pytest-html reports.

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

Or let the plugin start Mailpit in a Docker container for the session, with nothing to run before `pytest`:

```bash
pip install "pytest-mailpit[testcontainers]"
pytest --mailpit-container
```

The `mailpit_smtp` fixture is the host and port where the application under test should send its email, in both cases.

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

#### Attachments

`attachment()` finds the one attachment with a file name and content type, both with shell-style wildcards and case-insensitive; the content comes from the client:

```python
invoice = message.attachment("invoice-*.pdf", content_type="application/pdf")
assert invoice.size > 1000
assert mailpit.get_attachment(invoice).startswith(b"%PDF")

logo = message.attachment(content_type="image/*", include_inline=True)  # an embedded image
```

Like `link()`, it fails unless exactly one attachment matches, and lists the ones the message has:

```
Expected one attachment named 'receipt-*.pdf' in message 'Your invoice' to pytest-3f9a2c-7b1e4d9a@example.com, found 0.
Attachments in the message:
  invoice-1001.pdf (application/pdf, 12.3 kB)
```

#### Unsubscribe links

`unsubscribe_link()` returns the HTTP(S) link of the List-Unsubscribe header, and fails if the header is missing, Mailpit found problems in it, or it has no HTTP(S) link. With `one_click=True` it also checks what Gmail and Yahoo require from bulk senders: an HTTPS link and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058).

```python
def test_newsletter_can_be_unsubscribed_in_one_click(app_client, mailpit_inbox):
    app_client.post("/newsletter/subscribe", data={"email": mailpit_inbox.address})
    newsletter = mailpit_inbox.wait_for_message(subject="Our October news")

    link = newsletter.unsubscribe_link(one_click=True)
    app_client.post(link, data={"List-Unsubscribe": "One-Click"})
```

`message.list_unsubscribe` holds the header as Mailpit parsed it: `header`, `header_post`, `http_link`, `mailto_link`, `one_click` and `errors`.

#### Quality checks

Mailpit can check a message the way a careful reviewer would, and pytest-mailpit turns that into assertions:

```python
message.assert_links_work()  # no link answers with an error status, or not at all
message.assert_links_work(ignore=["linkedin.com"])  # sites that refuse automated requests
message.assert_html_support(at_least=90)  # % of the HTML and CSS that email clients support
```

A failure lists the broken links with their status, or the HTML and CSS features that hold the message back, with their pages on [caniemail.com](https://www.caniemail.com/):

```
2 of 5 links in message 'Welcome' to pytest-3f9a2c-7b1e4d9a@example.com are broken:
  404 Not Found  https://shop.example.com/old-page
  no such host   https://nowhere.invalid/
```

Mailpit sends a HEAD request to every link, so the links must be reachable from where Mailpit runs. Since Mailpit 1.29.2 it refuses to check private and internal addresses, such as `localhost` or a Docker service; to check links to the application under test, start Mailpit with `MP_ALLOW_INTERNAL_HTTP_REQUESTS=true`. `message.check_links()` and `message.check_html()` return the full results without asserting.

#### In the browser

`link()` finds a link in the HTML, but not whether the recipient can see and click it. `message.open(page)` shows the email in a browser page as its recipient would, inline images included, so the test can click through like a person:

```python
import re

from playwright.sync_api import expect


def test_confirmation_email(page, app_client, mailpit_inbox):
    app_client.post("/sign-up", data={"email": mailpit_inbox.address})
    message = mailpit_inbox.wait_for_message(subject="Confirm your email")

    message.open(page)
    page.get_by_role("link", name="Confirm your email").click()

    expect(page).to_have_url(re.compile("/welcome"))
```

`message.screenshot(page, path="confirm.png")` returns a PNG of the whole email, for a report or a visual comparison. Both work with a Playwright `Page`, such as pytest-playwright's `page` fixture, and with anything else that has `goto()`; pytest-mailpit does not depend on Playwright. If Mailpit asks for a password, give the browser context its credentials:

```python
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    credentials = {"username": "qa", "password": os.environ["MAILPIT_PASSWORD"]}
    return {**browser_context_args, "http_credentials": credentials}
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

### When sending fails

Mailpit's [Chaos](https://mailpit.axllent.org/docs/integration/chaos/) makes its SMTP server reject messages on purpose, so a test can check what the application does when email cannot be sent: show an error, retry, or queue the message. `mailpit_chaos` sets the errors for one test and restores what Mailpit had before:

```python
def test_sign_up_while_email_is_down(app_client, mailpit_chaos, mailpit_inbox):
    mailpit_chaos.reject_recipients(451)  # "try again later"

    response = app_client.post("/sign-up", data={"email": mailpit_inbox.address})

    assert "We could not send the confirmation email" in response.text
    mailpit_inbox.assert_no_message()
```

`reject_senders()` fails `MAIL FROM`, `reject_recipients()` fails `RCPT TO` and `reject_authentication()` fails `AUTH`. Each takes the SMTP error code, from 400 to 599, and a `probability` in percent, 100 by default; a lower one makes delivery flaky. `reset()` turns every error off, for example to check that the application sends the email when it retries.

Mailpit must run with Chaos enabled, `MP_ENABLE_CHAOS=true`; the container of `mailpit_container` has it. The errors apply to every message Mailpit receives, so pytest-xdist workers sharing one Mailpit would get each other's errors: give each worker its own with `mailpit_container = true`, or run the Chaos tests without `-n`.

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

It covers searching, reading whole messages, headers, the raw source and parts, deleting by IDs or by search, read status, waiting and Chaos (`chaos()`, `set_chaos()`). An empty list of IDs never reaches Mailpit, which would otherwise delete or change every message.

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
| List and attach a failed test's messages in reports | | | `mailpit_report_messages` | `true` |
| When Mailpit cannot be reached: `fail` or `skip` | | | `mailpit_unreachable` | `fail` |
| Mailpit's SMTP server, for `mailpit_smtp` | | `MAILPIT_SMTP` | `mailpit_smtp` | `localhost:1025` |
| Start Mailpit in a Docker container for the session | `--mailpit-container` | | `mailpit_container` | `false` |
| The image of that container | | | `mailpit_container_image` | `axllent/mailpit` |

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

With pytest-xdist, `pytest -n auto` needs nothing extra. Every address includes the worker (`pytest-gw3-...`), waiting matches it exactly, and cleanup deletes only that test's messages, so workers sharing one Mailpit never interfere. The exception is [`mailpit_chaos`](#when-sending-fails), whose errors reach every worker.

### When a test fails

The failed test's messages stay in Mailpit (`mailpit_keep_on_failure`), and its report lists them:

```
----------- Mailpit messages to pytest-3f9a2c-7b1e4d9a@example.com ------------
Messages to pytest-3f9a2c-7b1e4d9a@example.com (1):
  Received (UTC)  To                                  Subject
  09:14:03        pytest-3f9a2c-7b1e4d9a@example.com  Welcome to the shop
Mailpit: http://localhost:8025/
```

With [Allure](https://allurereport.org/docs/pytest/) (`--alluredir`) or [pytest-html](https://pytest-html.readthedocs.io/) (`--html`), the emails themselves are attached too, so a CI report keeps them after Mailpit is gone:

- **Allure**: the table above, each email as HTML (or text when it has no HTML part), and its source as an `.eml` file.
- **pytest-html**: a link to each email in Mailpit's web UI, and the email itself, shown in a sandboxed frame that keeps its styles and scripts out of the report.

The ten newest emails of each inbox are attached, and only when the test fails. Emails can hold tokens or personal data; set `mailpit_report_messages = false` to keep them out of reports and CI artifacts.

Mailpit keeps only the newest 500 messages by default (`MP_MAX_MESSAGES`) and deletes the others every minute, so kept messages do not stay forever. When tests failed and Mailpit holds 450 messages or more at the end of the run, a warning says so; if your Mailpit has a higher limit, silence it with `filterwarnings = ignore:Mailpit at .* holds:pytest_mailpit.MailpitWarning`.

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
        env:
          MP_SMTP_DISABLE_RDNS: "true"  # no reverse DNS lookups, which delay messages
          MP_ENABLE_CHAOS: "true"  # for mailpit_chaos
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install -e . pytest-mailpit
      # Your application sends email to localhost:1025.
      - run: pytest
```

### Recipes

- [docker compose](https://github.com/Nikolay-Chillev/pytest-mailpit/tree/main/examples/docker-compose): Mailpit next to the application, the tests on the host, and how the two find each other.
- [Testcontainers](https://github.com/Nikolay-Chillev/pytest-mailpit/tree/main/examples/testcontainers): `mailpit_container = true`, and the plugin starts Mailpit for the session; or start your own container and point the plugin at it.
- [Migrating from MailHog](https://github.com/Nikolay-Chillev/pytest-mailpit/blob/main/docs/migrating-from-mailhog.md): the container settings, the API and the message fields, call by call.

Both examples run in CI on every change.

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

The integration tests need a running Mailpit that may check links to internal addresses:

```bash
docker run -d -p 8025:8025 -p 1025:1025 -e MP_ALLOW_INTERNAL_HTTP_REQUESTS=true axllent/mailpit
pytest -m integration
```

## License

[MIT](https://github.com/Nikolay-Chillev/pytest-mailpit/blob/main/LICENSE)
