"""Mailpit's Chaos: SMTP errors on purpose, to test how an application handles them."""

import dataclasses

from pytest_mailpit.client import MailpitClient
from pytest_mailpit.models import ChaosTrigger, ChaosTriggers


class Chaos:
    """Makes Mailpit's SMTP server reject messages; the ``mailpit_chaos`` fixture.

    Each method sets one kind of error and keeps the others. ``code`` is the
    SMTP reply code: a 4xx code tells the application to try again later, a
    5xx code that sending failed for good. ``probability`` is the chance of
    the error, in percent.

    The errors apply to every message Mailpit receives, whoever sends it,
    until :meth:`reset`. After the test, the fixture restores the triggers
    Mailpit had before it.
    """

    def __init__(self, client: MailpitClient) -> None:
        self._client = client

    def __repr__(self) -> str:
        return f"Chaos({self._client.url!r})"

    @property
    def triggers(self) -> ChaosTriggers:
        """The errors Mailpit returns now."""
        return self._client.chaos()

    def reject_senders(self, code: int = 451, *, probability: int = 100) -> None:
        """Fail ``MAIL FROM``: Mailpit refuses the message before its recipients."""
        self._set(sender=_trigger(code, probability))

    def reject_recipients(self, code: int = 451, *, probability: int = 100) -> None:
        """Fail ``RCPT TO``, for each recipient of a message."""
        self._set(recipient=_trigger(code, probability))

    def reject_authentication(self, code: int = 535, *, probability: int = 100) -> None:
        """Fail ``AUTH``. Mailpit offers SMTP authentication only when it is set up,
        e.g. with ``MP_SMTP_AUTH_ACCEPT_ANY`` and ``MP_SMTP_AUTH_ALLOW_INSECURE``."""
        self._set(authentication=_trigger(code, probability))

    def reset(self) -> None:
        """Turn every error off."""
        self._client.set_chaos(ChaosTriggers())

    def _set(self, **changes: ChaosTrigger) -> None:
        # Mailpit replaces all the triggers at once, so the others are sent unchanged.
        self._client.set_chaos(dataclasses.replace(self.triggers, **changes))


def _trigger(code: int, probability: int) -> ChaosTrigger:
    if not 400 <= code <= 599:
        raise ValueError(f"code must be an SMTP error code from 400 to 599, got {code!r}")
    if not 0 <= probability <= 100:
        raise ValueError(f"probability must be a percentage from 0 to 100, got {probability!r}")
    return ChaosTrigger(code, probability)
