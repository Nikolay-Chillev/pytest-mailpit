from collections.abc import Iterator
from typing import Any

import pytest
import responses

from pytest_mailpit import MailpitAssertionError, MailpitClient, Message
from tests import samples

URL = "http://mailpit.test:8025/mailpit/"
ID = samples.MESSAGE["ID"]


class FakePage:
    """Records what a Playwright page would be asked to do."""

    def __init__(self) -> None:
        self.visited: list[str] = []
        self.screenshots: list[dict[str, Any]] = []

    def goto(self, url: str, /) -> None:
        self.visited.append(url)

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
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
