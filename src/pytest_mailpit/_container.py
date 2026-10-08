"""Mailpit in a Docker container for the test session, through Testcontainers."""

from typing import Any

# Settings of the container: no reverse DNS lookups, which delay every message
# by seconds in containers, and Chaos, so mailpit_chaos works.
CONTAINER_ENV = {"MP_SMTP_DISABLE_RDNS": "true", "MP_ENABLE_CHAOS": "true"}


def container_class() -> Any:
    """Testcontainers' MailpitContainer. Raises ImportError if it is not installed."""
    try:
        from testcontainers.community.mailpit import MailpitContainer
    except ImportError:
        # Testcontainers before 4.15 kept it here.
        from testcontainers.mailpit import MailpitContainer
    return MailpitContainer


def testcontainers_installed() -> bool:
    try:
        container_class()
    except ImportError:
        return False
    return True


def start_container(image: str) -> Any:
    container = container_class()(image)
    for name, value in CONTAINER_ENV.items():
        container = container.with_env(name, value)
    return container.start()
