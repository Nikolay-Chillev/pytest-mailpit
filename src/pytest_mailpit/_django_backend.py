"""The email backend of ``mailpit_django`` for projects on the ``EMAIL_*`` settings.

Django imports it by name, from ``EMAIL_BACKEND``, only while the fixture is on.
"""

from typing import Any

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

from pytest_mailpit._django import quiet_email_settings


class EmailBackend(SMTPBackend):  # type: ignore[misc]
    """Django's SMTP backend, without the login and TLS that Mailpit does not need.

    Blanking ``EMAIL_HOST_USER`` and the TLS settings instead would change
    what the application sends: a sender taken from ``EMAIL_HOST_USER``, for
    example, would become ``DEFAULT_FROM_EMAIL``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        with quiet_email_settings():  # it reads EMAIL_HOST and the others
            super().__init__(*args, **kwargs)
        self.username = self.password = ""
        self.use_tls = self.use_ssl = False
