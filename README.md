# pytest-mailpit

pytest fixtures and a typed client for testing real emails with [Mailpit](https://mailpit.axllent.org) — parallel-safe, no sleeps.

> **Status: early development.** Nothing is released yet. This page describes what the first version will do; feedback on it is very welcome in [Discussions](https://github.com/Nikolay-Chillev/pytest-mailpit/discussions).

## Why

Mailpit catches the emails your application sends in development and CI. Testing them from pytest usually means writing the same glue in every project's `conftest.py`: read the Mailpit URL from an environment variable, clear the mailbox, poll in a loop until the email arrives, and pull the link or code out with a regular expression. Clearing the shared mailbox also breaks parallel runs with pytest-xdist.

pytest-mailpit replaces that glue with a plugin you install once.

## Planned for the first release

- **Fixtures that work without configuration:** a Mailpit client and a per-test inbox. The URL comes from a command-line option, the `MAILPIT_URL` environment variable or an ini setting, and defaults to `http://localhost:8025`.
- **A unique address for every test**, so tests do not see each other's emails, also under pytest-xdist. After the test, only that test's emails are deleted.
- **Waiting instead of sleeping:** wait for one email, for several, or check that no email arrives, with a timeout.
- **Links and codes:** extract links from the HTML or text part, and one-time codes from the body.
- **Failure messages that help:** when an email does not arrive, the failure shows what was expected and which emails did arrive.
- **The whole message:** subject, recipients, text, HTML, headers, attachments and the raw source, as typed models.
- **Basic auth, HTTPS and a custom web root**, on Windows, macOS and Linux.

## Where it fits

| Layer | Typical tool | Use it when |
|---|---|---|
| In-process outbox | pytest-django `mailoutbox`, Flask-Mail `record_messages` | The code under test sends email from the test process |
| In-process SMTP server | smtpdfix, pytest-localserver | The application can be pointed at the fixture's port |
| **Mailpit + pytest-mailpit** | Mailpit in Docker or CI | The email leaves the test process: background workers, Docker, a backend in another language, staging, end-to-end tests with Playwright |
| Hosted inboxes | Mailosaur, MailSlurp, Mailtrap | You need real external inboxes or deliverability tests |

## Roadmap

- **0.1** — client, fixtures, waiting, link and code extraction, informative failures
- **0.2** — attachments, List-Unsubscribe checks, attaching emails to Allure and pytest-html reports, recipes for GitHub Actions and docker compose, migration guide from MailHog
- **0.3** — Mailpit's Chaos feature (simulated SMTP errors), the Send API, a Playwright helper
- **0.4** — an optional Testcontainers fixture
- **0.5** — an async client
- **1.0** — a stable API with a deprecation policy

Planned support: Python 3.11+, pytest 8.4+, Mailpit 1.22+.

## How do you test emails today?

Before the API is fixed, it helps to hear how you test emails now and what gets in your way. Open a [discussion](https://github.com/Nikolay-Chillev/pytest-mailpit/discussions) or an [issue](https://github.com/Nikolay-Chillev/pytest-mailpit/issues).

## License

[MIT](LICENSE)
