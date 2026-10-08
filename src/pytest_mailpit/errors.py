"""Exceptions raised by pytest-mailpit."""


class MailpitError(Exception):
    """Base class for all errors raised by pytest-mailpit."""


class MailpitConnectionError(MailpitError):
    """Mailpit could not be reached: wrong URL, server not running, network or TLS error."""


class MailpitAssertionError(MailpitError, AssertionError):
    """An expectation about the mailbox failed: a message did not arrive, arrived
    when none should have, or a link or code could not be found.

    It is an AssertionError, so pytest reports it as a test failure, not as an error.
    """


class MailpitAPIError(MailpitError):
    """Mailpit answered with an error status, or with something that is not its API."""

    def __init__(self, method: str, url: str, status_code: int, detail: str) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.detail = detail
        message = f"{method} {url} returned HTTP {status_code}"
        super().__init__(f"{message}: {detail}" if detail else message)


class MailpitWarning(UserWarning):
    """Something pytest-mailpit could work around but you should know about,
    such as an unsupported Mailpit version or messages it could not delete."""
