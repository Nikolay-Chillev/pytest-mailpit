"""pytest fixtures and a typed client for testing real emails with Mailpit."""

from importlib.metadata import version

from pytest_mailpit.aio import AsyncInbox, AsyncMailpitClient
from pytest_mailpit.chaos import Chaos
from pytest_mailpit.client import MailpitClient
from pytest_mailpit.config import MailpitConfig, SMTPServer
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
    ChaosTrigger,
    ChaosTriggers,
    HTMLCheck,
    HTMLWarning,
    LinkCheck,
    LinkStatus,
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
    "AsyncInbox",
    "AsyncMailpitClient",
    "Attachment",
    "Chaos",
    "ChaosTrigger",
    "ChaosTriggers",
    "HTMLCheck",
    "HTMLWarning",
    "Inbox",
    "LinkCheck",
    "LinkStatus",
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
    "SMTPServer",
    "ServerInfo",
    "__version__",
    "build_query",
    "quote",
]
