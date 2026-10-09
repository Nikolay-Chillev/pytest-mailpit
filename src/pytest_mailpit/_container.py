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
    container = plain(container_class())(image)
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


def plain(base: Any) -> Any:
    """MailpitContainer as a plain Mailpit, the one ``docker run axllent/mailpit`` gives.

    Testcontainers gives Mailpit a self-signed certificate, so it offers
    STARTTLS, and SMTP clients that upgrade whenever they can and check the
    certificate (Go's net/smtp, nodemailer, aiosmtplib) refuse to send. Its
    SMTP login, which accepts any user, stays, without TLS.
    """

    class PlainMailpitContainer(base):  # type: ignore[misc]
        def _configure(self) -> None:
            super()._configure()
            without_tls(self)

    return PlainMailpitContainer


def without_tls(container: Any) -> None:
    for name in ("MP_SMTP_TLS_CERT", "MP_SMTP_TLS_KEY"):
        container.env.pop(name, None)
    for path in (
        getattr(container, "tls_cert_file", None),
        getattr(container, "tls_key_file", None),
    ):
        if path is not None:
            container.volumes.pop(str(path), None)
    container.with_env("MP_SMTP_AUTH_ALLOW_INSECURE", "true")


def _stop(container: Any) -> None:
    # If even that fails, Testcontainers' Ryuk removes the container when pytest exits.
    with contextlib.suppress(Exception):
        container.stop()
