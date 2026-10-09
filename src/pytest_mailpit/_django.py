"""Django's email in Mailpit: the settings of ``mailpit_django``, and a hint for failures.

Nothing here imports Django: pytest-mailpit works without it.
"""

import contextlib
import sys
import warnings
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pytest_mailpit.config import SMTPServer

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# Django's SMTP backend without login or TLS: see _django_backend.
MAILPIT_BACKEND = "pytest_mailpit._django_backend.EmailBackend"
LOCMEM_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
OUTBOX_HINT = (
    "Django keeps email in memory during tests (django.core.mail.outbox): if the test's "
    "process sends this email, add the mailpit_django fixture to send it to Mailpit."
)


def email_settings(
    version: tuple[Any, ...], mailers: Mapping[str, Any] | None, smtp: "SMTPServer"
) -> dict[str, Any]:
    """The Django settings that send all email over SMTP to Mailpit.

    A Django 6.1 project that defines ``MAILERS`` gets every mailer pointed at
    Mailpit. Others, older versions and 6.1 projects still on the deprecated
    ``EMAIL_*`` settings, get ``EMAIL_BACKEND``, ``EMAIL_HOST`` and
    ``EMAIL_PORT``, as Django's test runner decides too. ``EMAIL_HOST_USER``
    and the TLS settings stay as they are: code may read them, e.g. as the
    sender, and the backend leaves them out when it talks to Mailpit.
    """
    if version >= (6, 1) and mailers is not None:
        return {
            "MAILERS": {
                alias: {"BACKEND": SMTP_BACKEND, "OPTIONS": {"host": smtp.host, "port": smtp.port}}
                for alias in (mailers or {"default": {}})
            }
        }
    return {"EMAIL_BACKEND": MAILPIT_BACKEND, "EMAIL_HOST": smtp.host, "EMAIL_PORT": smtp.port}


@contextlib.contextmanager
def quiet_email_settings() -> Iterator[None]:
    """No warnings from Django 6.1 for reading or setting the deprecated ``EMAIL_*`` settings.

    The project chose them; Django would blame pytest-mailpit, which touches
    them on its behalf, and under ``-W error`` the warning would be an error.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"The EMAIL_\w+ setting is deprecated")
        yield


def outbox_hint() -> str:
    """For a message that did not arrive: whether Django kept it in memory instead."""
    conf = sys.modules.get("django.conf")
    if conf is None or not conf.settings.configured:
        return ""
    with quiet_email_settings():
        in_memory = keeps_email_in_memory(conf.settings, version=sys.modules["django"].VERSION)
    return OUTBOX_HINT if in_memory else ""


def keeps_email_in_memory(settings: Any, *, version: tuple[Any, ...]) -> bool:
    """Whether Django sends email to its in-memory outbox, as during tests.

    Django 6.1 uses ``MAILERS`` when a project defines it; older versions
    ignore that setting and use ``EMAIL_BACKEND``.
    """
    mailers = getattr(settings, "MAILERS", None) if version >= (6, 1) else None
    if mailers is not None:
        return any(config.get("BACKEND") == LOCMEM_BACKEND for config in mailers.values())
    return getattr(settings, "EMAIL_BACKEND", None) == LOCMEM_BACKEND
