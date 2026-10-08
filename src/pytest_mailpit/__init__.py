"""pytest fixtures and a typed client for testing real emails with Mailpit."""

from importlib.metadata import version

from pytest_mailpit.client import MailpitClient
from pytest_mailpit.config import MailpitConfig
from pytest_mailpit.errors import (
    MailpitAPIError,
    MailpitAssertionError,
    MailpitConnectionError,
    MailpitError,
    MailpitWarning,
)
from pytest_mailpit.inbox import Inbox
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
    "Inbox",
    "ListUnsubscribe",
    "MailpitAPIError",
    "MailpitAssertionError",
    "MailpitClient",
    "MailpitConfig",
    "MailpitConnectionError",
    "MailpitError",
    "MailpitWarning",
    "Message",
    "MessageList",
    "MessageSummary",
    "ServerInfo",
    "__version__",
    "build_query",
    "quote",
]
