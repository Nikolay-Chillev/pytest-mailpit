"""Mailpit in a Docker container for the test session, through Testcontainers."""

import contextlib
import warnings
from typing import Any

# Settings of the container: no reverse DNS lookups, which delay every message
# by seconds in containers; Chaos, so mailpit_chaos works; and no asking GitHub
# for the latest release, which can hold up a fresh container for 10 s.
CONTAINER_ENV = {
    "MP_SMTP_DISABLE_RDNS": "true",
    "MP_ENABLE_CHAOS": "true",
    "MP_DISABLE_VERSION_CHECK": "true",
}


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
    try:
        with warnings.catch_warnings():
            # Testcontainers' own deprecations, such as of wait_for_logs() in
            # MailpitContainer.start(): with -W error they would end the start
            # after the container is running.
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="testcontainers")
            return container.start()
    except BaseException:
        _stop(container)  # it may be running already
        raise


def _stop(container: Any) -> None:
    # If even that fails, Testcontainers' Ryuk removes the container when pytest exits.
    with contextlib.suppress(Exception):
        container.stop()
