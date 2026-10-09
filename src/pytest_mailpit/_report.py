"""Text tables of messages, for failure messages."""

from collections.abc import Sequence
from datetime import UTC

from pytest_mailpit.models import MessageSummary

_TO_WIDTH = 36
_SUBJECT_WIDTH = 60


def message_table(summaries: Sequence[MessageSummary]) -> str:
    """One line per message: when it arrived (UTC), recipients, subject."""
    rows = [("Received (UTC)", "To", "Subject")]
    # The date too when the messages are from more than one day, as on a Mailpit
    # shared for a long time.
    days = {summary.created.astimezone(UTC).date() for summary in summaries}
    received = "%Y-%m-%d %H:%M:%S" if len(days) > 1 else "%H:%M:%S"
    for summary in summaries:
        recipients = [address.address for address in (*summary.to, *summary.cc, *summary.bcc)]
        to = recipients[0] if recipients else "-"
        if len(recipients) > 1:
            to += f" (+{len(recipients) - 1})"
        rows.append(
            (
                summary.created.astimezone(UTC).strftime(received),
                _shorten(to, _TO_WIDTH),
                _shorten(summary.subject or "(no subject)", _SUBJECT_WIDTH),
            )
        )
    widths = [max(len(row[column]) for row in rows) for column in range(2)]
    return "\n".join(
        f"  {received:<{widths[0]}}  {to:<{widths[1]}}  {subject}".rstrip()
        for received, to, subject in rows
    )


def _shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."
