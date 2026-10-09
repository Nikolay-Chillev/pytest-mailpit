import warnings
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import responses

from pytest_mailpit import MailpitAssertionError, MailpitClient, Message
from tests import samples

URL = "http://mailpit.test:8025/mailpit/"
ID = samples.MESSAGE["ID"]


class FakePage:
    """Records what a Playwright page would be asked to do; goto() answers with ``status``."""

    def __init__(self, status: int = 200) -> None:
        self.visited: list[str] = []
        self.screenshots: list[dict[str, Any]] = []
        self.status = status

    def goto(self, url: str, /) -> SimpleNamespace:
        self.visited.append(url)
        return SimpleNamespace(status=self.status)

    def screenshot(self, *, path: str | Path | None = None, full_page: bool = False) -> bytes:
        self.screenshots.append({"path": path, "full_page": full_page})
        return b"\x89PNG..."


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/message/{ID}", json=samples.MESSAGE)
        mock.get(
            f"{URL}api/v1/message/text-only", json=samples.MESSAGE | {"ID": "text-only", "HTML": ""}
        )
        yield mock


def test_html_url_is_mailpits_rendering_of_the_html_part() -> None:
    client = MailpitClient("http://user:secret@mailpit.test:8025/mailpit")

    assert client.html_url("Aa1Bb2") == "http://mailpit.test:8025/mailpit/view/Aa1Bb2.html"


def test_open_shows_the_message_and_returns_the_page(mocked: responses.RequestsMock) -> None:
    message = MailpitClient(URL).get_message(ID)
    page = FakePage()

    assert message.open(page) is page
    assert page.visited == [f"{URL}view/{ID}.html"]


def test_screenshot_takes_the_whole_message(mocked: responses.RequestsMock) -> None:
    message = MailpitClient(URL).get_message(ID)
    page = FakePage()

    assert message.screenshot(page, path="welcome.png") == b"\x89PNG..."
    assert page.visited == [f"{URL}view/{ID}.html"]
    assert page.screenshots == [{"path": "welcome.png", "full_page": True}]


def test_a_message_without_html_cannot_be_opened(mocked: responses.RequestsMock) -> None:
    message = MailpitClient(URL).get_message("text-only")
    page = FakePage()

    with pytest.raises(MailpitAssertionError, match="has no HTML part to open"):
        message.open(page)
    assert page.visited == []


def test_a_message_parsed_by_hand_cannot_be_opened() -> None:
    with pytest.raises(ValueError, match="not fetched by a MailpitClient"):
        Message.from_api(samples.MESSAGE).open(FakePage())


def test_a_screenshot_path_may_be_a_path(mocked: responses.RequestsMock, tmp_path: Path) -> None:
    page = FakePage()

    MailpitClient(URL).get_message(ID).screenshot(page, path=tmp_path / "email.png")

    assert page.screenshots == [{"path": tmp_path / "email.png", "full_page": True}]


@pytest.mark.parametrize(
    ("status", "hint"),
    [
        (401, "Give the browser context Mailpit's http_credentials."),
        (404, "The message was deleted meanwhile, by a cleanup or MP_MAX_MESSAGES."),
        (500, "so the browser shows no message"),
    ],
)
def test_an_error_page_is_not_opened_silently(
    mocked: responses.RequestsMock, status: int, hint: str
) -> None:
    message = MailpitClient(URL).get_message(ID)

    with pytest.raises(MailpitAssertionError) as failure:
        message.open(FakePage(status))

    assert f"Mailpit answered {URL}view/{ID}.html with HTTP {status}" in str(failure.value)
    assert hint in str(failure.value)


def test_an_async_page_is_refused_instead_of_never_navigating(
    mocked: responses.RequestsMock,
) -> None:
    class AsyncPage:
        async def goto(self, url: str, /) -> None:
            pass

    message = MailpitClient(URL).get_message(ID)

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no "coroutine was never awaited"
        with pytest.raises(TypeError, match=r"await page.goto\(mailpit_async.html_url"):
            message.open(AsyncPage())
