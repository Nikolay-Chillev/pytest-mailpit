"""Settings of the pytest plugin."""

from dataclasses import dataclass, field
from typing import NamedTuple

from pytest_mailpit.client import DEFAULT_URL, MailpitClient

DEFAULT_IMAGE = "axllent/mailpit"


class SMTPServer(NamedTuple):
    """Where the application under test sends its email: Mailpit's SMTP server."""

    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


DEFAULT_SMTP = SMTPServer("localhost", 1025)


# Reserved for examples (RFC 2606), so it never reaches a real person, and
# unlike ".test" it passes the email validation of most applications.
DEFAULT_DOMAIN = "example.com"


@dataclass(frozen=True, slots=True)
class MailpitConfig:
    """The settings pytest-mailpit runs with, after command line options,
    environment variables and ini settings are applied."""

    url: str = DEFAULT_URL
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    # False skips TLS verification; a string is the path of a CA bundle.
    verify: bool | str = True
    wait_timeout: float = 10.0
    poll_interval: float = 0.5
    # Domain of the addresses mailpit_inbox creates.
    domain: str = DEFAULT_DOMAIN
    # Keep a failed test's messages in Mailpit, to look at them in its web UI.
    keep_on_failure: bool = True
    # Tag the kept messages with the test's name, to find them in Mailpit's web UI.
    tag_failures: bool = True
    # List a failed test's messages in its report and attach them to Allure and
    # pytest-html reports. Off for emails that must not end up in CI artifacts.
    report_messages: bool = True
    # Skip the tests that need Mailpit when it cannot be reached, instead of failing them.
    skip_if_unreachable: bool = False
    # Mailpit's SMTP server, for the mailpit_smtp fixture.
    smtp: SMTPServer = DEFAULT_SMTP
    # Start Mailpit in a Docker container for the session (Testcontainers), from this image.
    container: bool = False
    container_image: str = DEFAULT_IMAGE

    def client(self) -> MailpitClient:
        return MailpitClient(
            self.url,
            username=self.username,
            password=self.password,
            verify=self.verify,
            wait_timeout=self.wait_timeout,
            poll_interval=self.poll_interval,
        )
