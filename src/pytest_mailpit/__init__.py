"""pytest fixtures and a typed client for testing real emails with Mailpit."""

from importlib.metadata import version

from pytest_mailpit.client import MailpitClient
from pytest_mailpit.errors import MailpitAPIError, MailpitConnectionError, MailpitError
from pytest_mailpit.models import (
    Address,
    Attachment,
    ListUnsubscribe,
    Message,
    MessageList,
    MessageSummary,
    ServerInfo,
)
from pytest_mailpit.search import build_query, quote

__version__ = version("pytest-mailpit")

__all__ = [
    "Address",
    "Attachment",
    "ListUnsubscribe",
    "MailpitAPIError",
    "MailpitClient",
    "MailpitConnectionError",
    "MailpitError",
    "Message",
    "MessageList",
    "MessageSummary",
    "ServerInfo",
    "__version__",
    "build_query",
    "quote",
]
