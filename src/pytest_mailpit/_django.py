"""Django's email in Mailpit: the settings of ``mailpit_django``, and a hint for failures.

Nothing here imports Django: pytest-mailpit works without it.
"""

import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pytest_mailpit.config import SMTPServer

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
LOCMEM_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
OUTBOX_HINT = (
    "Django keeps email in memory during tests (django.core.mail.outbox): "
    "add the mailpit_django fixture to send it to Mailpit."
)


def email_settings(
    version: tuple[Any, ...], mailers: Mapping[str, Any] | None, smtp: "SMTPServer"
) -> dict[str, Any]:
    """The Django settings that send all email over SMTP to Mailpit.

    Django 6.1 configures email with ``MAILERS``: every mailer the project
    defines, or ``default``, goes to Mailpit. Older versions use
    ``EMAIL_BACKEND`` and the other ``EMAIL_*`` settings, which 6.1 deprecates.
    """
    if version >= (6, 1):
        return {
            "MAILERS": {
                alias: {"BACKEND": SMTP_BACKEND, "OPTIONS": {"host": smtp.host, "port": smtp.port}}
                for alias in (mailers or {"default": {}})
            }
        }
    return {
        "EMAIL_BACKEND": SMTP_BACKEND,
        "EMAIL_HOST": smtp.host,
        "EMAIL_PORT": smtp.port,
        # Mailpit needs no login and no TLS, unless it is set up for them.
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": False,
        "EMAIL_USE_SSL": False,
    }


def outbox_hint() -> str:
    """For a message that did not arrive: whether Django kept it in memory instead."""
    conf = sys.modules.get("django.conf")
    if conf is None or not conf.settings.configured:
        return ""
    return OUTBOX_HINT if keeps_email_in_memory(conf.settings) else ""


def keeps_email_in_memory(settings: Any) -> bool:
    """Whether Django sends email to its in-memory outbox, as during tests."""
    mailers = getattr(settings, "MAILERS", None)
    if mailers is not None:
        return any(config.get("BACKEND") == LOCMEM_BACKEND for config in mailers.values())
    return getattr(settings, "EMAIL_BACKEND", None) == LOCMEM_BACKEND
