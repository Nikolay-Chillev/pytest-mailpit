"""Settings of the pytest plugin."""

from dataclasses import dataclass, field

from pytest_mailpit.client import DEFAULT_URL, MailpitClient

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
    # List a failed test's messages in its report and attach them to Allure and
    # pytest-html reports. Off for emails that must not end up in CI artifacts.
    report_messages: bool = True
    # Skip the tests that need Mailpit when it cannot be reached, instead of failing them.
    skip_if_unreachable: bool = False

    def client(self) -> MailpitClient:
        return MailpitClient(
            self.url,
            username=self.username,
            password=self.password,
            verify=self.verify,
            wait_timeout=self.wait_timeout,
            poll_interval=self.poll_interval,
        )
