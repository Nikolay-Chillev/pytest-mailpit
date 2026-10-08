# Changelog

All notable changes to pytest-mailpit are listed here. The project follows
[Semantic Versioning](https://semver.org/); before 1.0 the API may still change
in any release.

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

[0.1.0a1]: https://github.com/Nikolay-Chillev/pytest-mailpit/releases/tag/v0.1.0a1
