# Changelog

All notable changes to pytest-mailpit are listed here. The project follows
[Semantic Versioning](https://semver.org/); before 1.0 the API may still change
in any release.

## [Unreleased]

### Added

- `Message.assert_links_work()`: fails the test if a link in the message answers with an error status or not at all, using Mailpit's link check; `ignore` skips links such as social networks, and a hint explains Mailpit's refusal to check internal addresses.
- `Message.assert_html_support(at_least=...)`: fails the test unless email clients support enough of the message's HTML and CSS, using Mailpit's HTML check (caniemail.com data), and lists the worst problems.
- `mailpit_container = true` (or `--mailpit-container`): the plugin starts Mailpit in a Docker container for the session through Testcontainers, on first use, with Chaos enabled and without reverse DNS lookups; every pytest-xdist worker gets its own. Install it with `pip install "pytest-mailpit[testcontainers]"`; `mailpit_container_image` picks the image, and the `mailpit_container` fixture is the container.
- `mailpit_smtp`: the host and port where the application under test sends email, from the container or from `MAILPIT_SMTP` / `mailpit_smtp` (default `localhost:1025`), as an `SMTPServer`.
- `mailpit_chaos`: makes Mailpit's SMTP server reject messages on purpose (Mailpit's Chaos, `MP_ENABLE_CHAOS=true`), to test how the application handles failed sending. `reject_senders()`, `reject_recipients()` and `reject_authentication()` take the SMTP error code and a probability; `reset()` turns every error off, and the fixture restores Mailpit's previous triggers after the test. It warns when pytest-xdist workers share one Mailpit.
- A warning at the end of the run when failed tests kept their messages and Mailpit holds 450 messages or more: with its default limit of 500 (`MP_MAX_MESSAGES`), Mailpit deletes the oldest every minute.
- `MailpitClient.chaos()` and `MailpitClient.set_chaos()`: Mailpit's Chaos triggers as `ChaosTriggers` and `ChaosTrigger`.
- `Message.open(page)`: shows the message's HTML in a browser page as its recipient would see it, inline images included, and returns the page, e.g. to click a link with Playwright. `Message.screenshot(page)` returns a PNG of the whole message. Neither needs Playwright installed; any page with `goto()` works.
- `MailpitClient.html_url()`: Mailpit's rendering of a message's HTML part.
- `Message.check_links()`, `Message.check_html()`, `MailpitClient.check_links()` and `MailpitClient.check_html()` return the full results: `LinkCheck`, `LinkStatus`, `HTMLCheck` and `HTMLWarning`. A message fetched by a client remembers it for these checks.

## [0.2.0] - 2026-10-08

### Added

- A failed test's emails are attached to Allure (`--alluredir`) and pytest-html (`--html`) reports, so CI reports keep them after Mailpit is gone. Allure gets each email as HTML or text and its source as an `.eml` file; pytest-html gets a link to the email in Mailpit and the email in a sandboxed frame. The ten newest emails of each inbox are attached.
- `mailpit_report_messages`: set it to `false` to keep a failed test's emails out of its report and attachments.
- `MailpitClient.view_url()`: the page of a message in Mailpit's web UI.
- `Message.attachment()`: the one attachment with a file name and content type, wildcards allowed; inline parts such as embedded images with `include_inline=True`. It fails the test unless exactly one matches, and lists the message's attachments.
- `MailpitClient.get_attachment()`: the content of an attachment. Attachments now know the message they belong to (`Attachment.message_id`).
- `Message.unsubscribe_link()`: the HTTP(S) link of the List-Unsubscribe header, failing the test if the header is missing, invalid or has no such link; with `one_click=True` it also checks the HTTPS link and `List-Unsubscribe-Post` that RFC 8058 one-click unsubscription needs.
- `ListUnsubscribe.http_link`, `mailto_link` and `one_click`.

### Documentation

- Recipes for docker compose and Testcontainers, run in CI on every change, and a guide for migrating from MailHog.

## [0.1.0a1] - 2026-10-08

The first release.

### Added

- **pytest plugin**, registered automatically:
  - `mailpit_inbox`: a unique address for every test, with waiting limited to it; after the test only its messages are deleted, so it is safe under pytest-xdist.
  - `mailpit_inbox_factory`: more inboxes for one test.
  - `mailpit`: a client for the configured server, shared by the session, with a clear message when Mailpit cannot be reached or wants a password.
  - `mailpit_config`: the settings in effect.
  - Settings from the command line, the environment and the ini file: URL, username and password, TLS verification, wait timeout, poll interval, inbox domain, keeping a failed test's messages, and skipping when Mailpit is unreachable.
  - `@pytest.mark.mailpit(timeout=...)` for one test's wait.
  - A failed test's report lists the messages sent to its inboxes.
- **Waiting** for one message, for several, or for none, with exact address matching, a time limit, and failures that list what arrived instead.
- **Links and one-time codes** found in a message's HTML and text.
- **`MailpitClient`**, a typed client for Mailpit's API: search, messages, headers, raw source, parts, deleting, read status and server time; it works under a web root, with basic auth and custom TLS verification.

[Unreleased]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.1.0a1...v0.2.0
[0.1.0a1]: https://github.com/Nikolay-Chillev/pytest-mailpit/releases/tag/v0.1.0a1
