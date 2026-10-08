# Changelog

All notable changes to pytest-mailpit are listed here. The project follows
[Semantic Versioning](https://semver.org/); before 1.0 the API may still change
in any release.

## [Unreleased]

### Fixed

- Requests to Mailpit no longer follow redirects. Behind a proxy that redirected, for example from http:// to https://, a 301 made the cleanup after every passing test delete every message in Mailpit, because requests sent the DELETE again without its list of IDs. A 302 turned deletes, tags and Chaos changes into GET requests that did nothing. A redirect is now an error that names the URL to use, and the check at the start of the session catches it before any test runs.
- The plugin no longer calls `/api/v1/info`. Before it answers, Mailpit asks GitHub for its latest release; where outbound connections hang, that took 10 s, as long as the client's timeout, so every test failed with "Cannot reach Mailpit" although Mailpit was up, and Mailpit's SMTP server waited meanwhile. The check at the start of the session and the 450-message warning use `/api/v1/messages`, and a Mailpit older than 1.22 is recognised by its missing `/api/v1/chaos`. `MailpitClient.info()` still works and says this in its docstring.
- The container of `mailpit_container` runs with `MP_DISABLE_VERSION_CHECK=true`.

## [0.4.0] - 2026-10-08

### Added

- `mailpit_django`: Django sends the test's email over SMTP to Mailpit instead of keeping it in `django.core.mail.outbox`, so `mailpit_inbox` gets it as the recipient does. It sets `MAILERS` on Django 6.1 and newer, and `EMAIL_BACKEND`, `EMAIL_HOST` and `EMAIL_PORT` on older versions.
- When a wait for a message times out while Django keeps email in memory, the failure says so and suggests `mailpit_django`.
- `mailpit_async_inbox` and `mailpit_async`: the inbox and the client for async tests, with `AsyncInbox` and `AsyncMailpitClient`. Waiting yields to the event loop between polls, so an application that sends email from the same loop keeps running. No async HTTP library is needed: each request runs in a worker thread.
- A failed test's kept messages are tagged with its name, such as `failed test_sign_up`, keeping the tags the application gave them, and the report links to Mailpit's search for the tag. `mailpit_tag_failures = false` turns it off.
- `MailpitClient.set_tags()` and `MailpitClient.search_url()`, and their `AsyncMailpitClient` versions.

### Documentation

- Django, Flask and FastAPI examples, run in CI on every change; Django with 5.2 and 6.1, and FastAPI with an async test.

## [0.3.0] - 2026-10-08

### Added

- `mailpit_container = true` (or `--mailpit-container`): the plugin starts Mailpit in a Docker container for the session through Testcontainers, on first use, with Chaos enabled and without reverse DNS lookups; every pytest-xdist worker gets its own. Install it with `pip install "pytest-mailpit[testcontainers]"`; `mailpit_container_image` picks the image, and the `mailpit_container` fixture is the container.
- `mailpit_smtp`: the host and port where the application under test sends email, from the container or from `MAILPIT_SMTP` / `mailpit_smtp` (default `localhost:1025`), as an `SMTPServer`.
- `mailpit_chaos`: makes Mailpit's SMTP server reject messages on purpose (Mailpit's Chaos, `MP_ENABLE_CHAOS=true`), to test how the application handles failed sending. `reject_senders()`, `reject_recipients()` and `reject_authentication()` take the SMTP error code and a probability; `reset()` turns every error off, and the fixture restores Mailpit's previous triggers after the test. It warns when pytest-xdist workers share one Mailpit.
- `MailpitClient.chaos()` and `MailpitClient.set_chaos()`: Mailpit's Chaos triggers as `ChaosTriggers` and `ChaosTrigger`.
- `Message.assert_links_work()`: fails the test if a link in the message answers with an error status or not at all, using Mailpit's link check; `ignore` skips links such as social networks, and a hint explains Mailpit's refusal to check internal addresses.
- `Message.assert_html_support(at_least=...)`: fails the test unless email clients support enough of the message's HTML and CSS, using Mailpit's HTML check (caniemail.com data), and lists the worst problems.
- `Message.check_links()`, `Message.check_html()`, `MailpitClient.check_links()` and `MailpitClient.check_html()` return the full results: `LinkCheck`, `LinkStatus`, `HTMLCheck` and `HTMLWarning`. A message fetched by a client remembers it for these checks.
- `Message.open(page)`: shows the message's HTML in a browser page as its recipient would see it, inline images included, and returns the page, e.g. to click a link with Playwright. `Message.screenshot(page)` returns a PNG of the whole message. Neither needs Playwright installed; any page with `goto()` works.
- `MailpitClient.html_url()`: Mailpit's rendering of a message's HTML part.
- A warning at the end of the run when failed tests kept their messages and Mailpit holds 450 messages or more: with its default limit of 500 (`MP_MAX_MESSAGES`), Mailpit deletes the oldest every minute.

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

[Unreleased]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nikolay-Chillev/pytest-mailpit/compare/v0.1.0a1...v0.2.0
[0.1.0a1]: https://github.com/Nikolay-Chillev/pytest-mailpit/releases/tag/v0.1.0a1
