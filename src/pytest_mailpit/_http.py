"""HTTP access to Mailpit: one requests session bound to the server's URL."""

import json
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from pytest_mailpit.errors import MailpitAPIError, MailpitConnectionError

MAX_DETAIL_CHARS = 500


class Transport:
    """Sends requests to paths relative to Mailpit's URL and turns failures into errors.

    The URL may include a web root (Mailpit's ``--webroot``), e.g.
    ``http://localhost:8025/mailpit/``.
    """

    def __init__(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        verify: bool | str = True,
        timeout: float = 10.0,
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"Expected the http:// or https:// URL of Mailpit, got {url!r}")
        self.base_url = url if url.endswith("/") else f"{url}/"
        # For messages: never show credentials given in the URL.
        self.display_url = _without_credentials(self.base_url)
        self._userinfo = parts.netloc.rpartition("@")[0]
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify
        if username is not None:
            self.session.auth = (username, password or "")

    def url(self, path: str) -> str:
        """Resolve ``path`` against Mailpit's URL; a leading slash is ignored."""
        return urljoin(self.base_url, path.lstrip("/"))

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> requests.Response:
        try:
            response = self.session.request(
                method, self.url(path), params=params, json=json_body, timeout=self.timeout
            )
        except requests.RequestException as error:
            # The error text can contain the requested URL, credentials included.
            reason = str(error).replace(f"{self._userinfo}@", "") if self._userinfo else error
            raise MailpitConnectionError(
                f"Cannot reach Mailpit at {self.display_url}: {reason}"
            ) from error
        if not response.ok:
            raise MailpitAPIError(
                method, _without_credentials(response.url), response.status_code, _detail(response)
            )
        return response

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.request("GET", path, params=params)
        try:
            return response.json()
        except ValueError:
            content_type = response.headers.get("Content-Type") or "no content type"
            raise MailpitAPIError(
                "GET",
                _without_credentials(response.url),
                response.status_code,
                f"expected JSON, got {content_type}. Is {self.display_url} the URL of Mailpit?",
            ) from None

    def close(self) -> None:
        self.session.close()


def _detail(response: requests.Response) -> str:
    """The error text of a response: Mailpit sends plain text, or JSON with an "Error" key."""
    text = response.text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        pass
    else:
        if isinstance(data, dict) and isinstance(data.get("Error"), str):
            text = data["Error"]
    if len(text) > MAX_DETAIL_CHARS:
        return f"{text[:MAX_DETAIL_CHARS]}... ({len(text) - MAX_DETAIL_CHARS} more characters)"
    return text


def _without_credentials(url: str) -> str:
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit(parts._replace(netloc=netloc))
