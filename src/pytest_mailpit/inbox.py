"""A unique address for one test, and the messages sent to it."""

import hashlib
import re
import secrets

from pytest_mailpit._report import message_table
from pytest_mailpit.client import MailpitClient
from pytest_mailpit.models import Message, MessageSummary
from pytest_mailpit.search import build_query


def unique_address(test_id: str, *, domain: str, worker: str | None = None) -> str:
    """An address no other test uses: "pytest-<worker>-<test>-<random>@<domain>".

    The test part is a short hash of the test ID, so messages of one test are
    easy to spot in Mailpit; the random part keeps reruns and repeated
    addresses within a test apart. Only lowercase letters, digits and hyphens
    are used, because applications often reject anything else, a "+" included.
    The local part stays far below the 64 characters email allows.
    """
    if not domain or "@" in domain or domain.strip() != domain:
        raise ValueError(f"Expected a domain such as example.com, got {domain!r}")
    test = hashlib.sha256(test_id.encode()).hexdigest()[:6]
    # pytest-xdist names workers "gw0", "gw1", ...; anything else is cut short.
    worker_part = re.sub(r"[^a-z0-9]", "", (worker or "").lower())[:16]
    parts = ["pytest", worker_part, test, secrets.token_hex(4)]
    return f"{'-'.join(part for part in parts if part)}@{domain}"


class Inbox:
    """An address that only one test uses, and the messages sent to it.

    The waiting methods match the address exactly, in To, Cc or Bcc, so tests
    sharing one Mailpit, in parallel too, never see each other's messages.
    """

    def __init__(self, client: MailpitClient, address: str, *, wait_timeout: float) -> None:
        self.client = client
        self.address = address
        self.wait_timeout = wait_timeout

    def __str__(self) -> str:
        return self.address

    def __repr__(self) -> str:
        return f"Inbox({self.address!r})"

    def wait_for_message(
        self,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        timeout: float | None = None,
    ) -> Message:
        """Wait until exactly one matching message has arrived, and return it.

        ``subject`` matches any part of the subject, ``sender`` the whole From
        address, and ``query`` adds a Mailpit search. Fails the test if none
        arrives within ``timeout`` seconds, or if more than one matches.
        """
        __tracebackhide__ = True
        return self.client.wait_for_message(
            query,
            recipient=self.address,
            sender=sender,
            subject=subject,
            timeout=self.wait_timeout if timeout is None else timeout,
        )

    def wait_for_messages(
        self,
        count: int,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        timeout: float | None = None,
    ) -> list[Message]:
        """Wait until exactly ``count`` matching messages have arrived; oldest first."""
        __tracebackhide__ = True
        return self.client.wait_for_messages(
            count,
            query,
            recipient=self.address,
            sender=sender,
            subject=subject,
            timeout=self.wait_timeout if timeout is None else timeout,
        )

    def assert_no_message(
        self,
        *,
        subject: str | None = None,
        sender: str | None = None,
        query: str | None = None,
        within: float = 2.0,
    ) -> None:
        """Fail the test if a matching message arrives within ``within`` seconds."""
        __tracebackhide__ = True
        self.client.assert_no_message(
            query, recipient=self.address, sender=sender, subject=subject, within=within
        )

    def messages(self) -> list[MessageSummary]:
        """The messages sent to the address so far, oldest first."""
        found = [
            summary
            for summary in self.client.search_all(build_query(addressed=self.address))
            if self._is_recipient(summary)
        ]
        found.reverse()
        return found

    def clear(self) -> None:
        """Delete the messages sent to the address, and no others.

        By ID: a search for the address would also delete the messages of any
        address that contains it, such as ``xa@example.com`` for ``a@example.com``.
        """
        self.client.delete_messages(summary.id for summary in self.messages())

    def describe(self, found: list[MessageSummary] | None = None) -> str:
        """The messages sent to the address, as a table, for a test report.

        ``found`` are the inbox's messages if they were fetched already.
        """
        if found is None:
            found = self.messages()
        if not found:
            return f"No messages to {self.address}.\nMailpit: {self.client.url}"
        return (
            f"Messages to {self.address} ({len(found)}):\n{message_table(found)}\n"
            f"Mailpit: {self.client.url}"
        )

    def _is_recipient(self, summary: MessageSummary) -> bool:
        address = self.address.lower()
        recipients = (*summary.to, *summary.cc, *summary.bcc)
        return any(recipient.address.lower() == address for recipient in recipients)
