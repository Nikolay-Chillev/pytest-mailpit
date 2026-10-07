import os
from urllib.parse import urlsplit

import pytest


@pytest.fixture(scope="session")
def mailpit_url() -> str:
    url = os.environ.get("MAILPIT_URL", "http://localhost:8025/")
    return url if url.endswith("/") else f"{url}/"


@pytest.fixture(scope="session")
def smtp_address() -> tuple[str, int]:
    """Host and port of Mailpit's SMTP server, from ``MAILPIT_SMTP`` (``host:port``)."""
    parts = urlsplit(f"//{os.environ.get('MAILPIT_SMTP', 'localhost:1025')}")
    return parts.hostname or "localhost", parts.port or 1025
