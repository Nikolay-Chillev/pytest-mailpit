from collections.abc import Iterator
from typing import Any

import pytest
import responses
from responses import matchers

from pytest_mailpit import (
    HTMLCheck,
    LinkCheck,
    LinkStatus,
    MailpitAssertionError,
    MailpitClient,
    Message,
)
from tests import samples

URL = "http://mailpit.test:8025/"
ID = samples.MESSAGE["ID"]
LINK_CHECK = f"{URL}api/v1/message/{ID}/link-check"
HTML_CHECK = f"{URL}api/v1/message/{ID}/html-check"


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/message/{ID}", json=samples.MESSAGE)
        yield mock


@pytest.fixture
def message(mocked: responses.RequestsMock) -> Message:
    return MailpitClient(URL).get_message(ID)


def link(url: str, code: int, status: str) -> dict[str, Any]:
    return {"URL": url, "StatusCode": code, "Status": status}


def html_check(supported: float, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "Total": {
            "Supported": supported,
            "Partial": 100 - supported,
            "Unsupported": 0.0,
            "Tests": 300,
            "Nodes": 12,
        },
        "Warnings": warnings or [],
        "Platforms": {"gmail": ["desktop-webmail", "android"]},
    }


def warning(title: str, unsupported: float, partial: float, found: int = 1) -> dict[str, Any]:
    return {
        "Slug": title.lower(),
        "Title": title,
        "Description": "",
        "URL": f"https://www.caniemail.com/features/{title.lower()}/",
        "Category": "css",
        "Score": {
            "Found": found,
            "Supported": 100 - unsupported - partial,
            "Partial": partial,
            "Unsupported": unsupported,
        },
    }


# Models


def test_link_status() -> None:
    assert LinkStatus("https://x.test/", 200, "OK").ok
    assert LinkStatus("https://x.test/", 301, "Moved Permanently").ok
    assert not LinkStatus("https://x.test/", 404, "Not Found").ok
    assert not LinkStatus("https://nowhere.invalid/", 0, "no such host").ok
    blocked = LinkStatus("http://localhost:8000/", 451, "Blocked private/reserved address")
    assert blocked.blocked
    assert not blocked.ok
    assert not LinkStatus("https://x.test/", 451, "Unavailable For Legal Reasons").blocked


def test_link_check_lists_the_broken_links() -> None:
    result = LinkCheck.from_api(
        {
            "Errors": 1,
            "Links": [
                link("https://x.test/", 200, "OK"),
                link("https://x.test/old", 404, "Not Found"),
            ],
        }
    )

    assert result.errors == 1
    assert [broken.url for broken in result.broken] == ["https://x.test/old"]


def test_html_check_parses_the_totals_and_warnings() -> None:
    result = HTMLCheck.from_api(
        html_check(87.5, [warning("Flexbox", unsupported=30, partial=10, found=3)])
    )

    assert (result.supported, result.partial, result.tests, result.nodes) == (87.5, 12.5, 300, 12)
    [flexbox] = result.warnings
    assert (flexbox.title, flexbox.found, flexbox.unsupported, flexbox.partial) == (
        "Flexbox",
        3,
        30,
        10,
    )
    assert flexbox.url == "https://www.caniemail.com/features/flexbox/"
    assert result.platforms == {"gmail": ["desktop-webmail", "android"]}


def test_empty_checks() -> None:
    assert LinkCheck.from_api({}) == LinkCheck(links=(), errors=0)
    assert HTMLCheck.from_api({}).warnings == ()


# The client


def test_check_links_can_follow_redirects(mocked: responses.RequestsMock) -> None:
    mocked.get(
        LINK_CHECK, json={"Errors": 0, "Links": []}, match=[matchers.query_param_matcher({})]
    )
    mocked.get(
        LINK_CHECK,
        json={"Errors": 0, "Links": []},
        match=[matchers.query_param_matcher({"follow": "true"})],
    )
    client = MailpitClient(URL)

    client.check_links(ID)
    client.check_links(ID, follow_redirects=True)


def test_messages_from_the_client_know_it(message: Message) -> None:
    assert message._client is not None


def test_messages_parsed_by_hand_cannot_ask_mailpit() -> None:
    with pytest.raises(ValueError, match="not fetched by a MailpitClient; ask the client"):
        Message.from_api(samples.MESSAGE).check_links()


def test_the_client_does_not_change_equality(message: Message) -> None:
    assert message == Message.from_api(samples.MESSAGE)


# assert_links_work


def test_working_links_pass(mocked: responses.RequestsMock, message: Message) -> None:
    mocked.get(LINK_CHECK, json={"Errors": 0, "Links": [link("https://x.test/", 200, "OK")]})

    assert message.assert_links_work().links[0].url == "https://x.test/"


def test_broken_links_fail_with_their_status(
    mocked: responses.RequestsMock, message: Message
) -> None:
    mocked.get(
        LINK_CHECK,
        json={
            "Errors": 2,
            "Links": [
                link("https://shop.example.test/", 200, "OK"),
                link("https://shop.example.test/old-page", 404, "Not Found"),
                link("https://nowhere.invalid/", 0, "no such host"),
            ],
        },
    )

    with pytest.raises(MailpitAssertionError) as raised:
        message.assert_links_work()

    assert str(raised.value) == (
        "2 of 3 links in message 'Поръчка №1001' to ivan@example.test are broken:\n"
        "  404 Not Found  https://shop.example.test/old-page\n"
        "  no such host   https://nowhere.invalid/"
    )


def test_ignored_links_are_not_held_against_the_message(
    mocked: responses.RequestsMock, message: Message
) -> None:
    mocked.get(
        LINK_CHECK,
        json={"Errors": 1, "Links": [link("https://social.example/shop", 403, "Forbidden")]},
    )

    assert message.assert_links_work(ignore=["social.example"]).errors == 1


def test_blocked_internal_links_get_a_hint(
    mocked: responses.RequestsMock, message: Message
) -> None:
    mocked.get(
        LINK_CHECK,
        json={
            "Errors": 1,
            "Links": [
                link("http://localhost:8000/confirm", 451, "Blocked private/reserved address")
            ],
        },
    )

    with pytest.raises(MailpitAssertionError) as raised:
        message.assert_links_work()

    assert "451 Blocked private/reserved address  http://localhost:8000/confirm" in str(
        raised.value
    )
    assert str(raised.value).endswith(
        "start Mailpit with MP_ALLOW_INTERNAL_HTTP_REQUESTS=true (--allow-internal-http-requests)."
    )


# assert_html_support


def test_enough_html_support_passes(mocked: responses.RequestsMock, message: Message) -> None:
    mocked.get(HTML_CHECK, json=html_check(92.3))

    assert message.assert_html_support(at_least=90).supported == 92.3


def test_too_little_html_support_lists_the_worst_problems(
    mocked: responses.RequestsMock, message: Message
) -> None:
    warnings = [
        warning(f"Feature {n}", unsupported=40 - n, partial=n, found=n) for n in range(1, 8)
    ]
    mocked.get(HTML_CHECK, json=html_check(72.46, warnings))

    with pytest.raises(MailpitAssertionError) as raised:
        message.assert_html_support(at_least=80)

    lines = str(raised.value).splitlines()
    assert lines[0] == (
        "Email clients support 72.5% of the HTML and CSS in message 'Поръчка №1001' to "
        "ivan@example.test, expected at least 80%."
    )
    assert lines[1] == "Worst problems (caniemail.com data):"
    assert lines[2] == (
        "  Feature 1: 39% of clients do not support it, 1% partly; used 1x  "
        "https://www.caniemail.com/features/feature 1/"
    )
    assert len(lines) == 2 + 5


def test_html_support_of_a_message_without_html(mocked: responses.RequestsMock) -> None:
    mocked.get(
        f"{URL}api/v1/message/text-only", json=samples.MESSAGE | {"ID": "text-only", "HTML": ""}
    )
    message = MailpitClient(URL).get_message("text-only")

    with pytest.raises(MailpitAssertionError, match="has no HTML part to check"):
        message.assert_html_support(at_least=50)


def test_too_little_html_support_without_warnings(
    mocked: responses.RequestsMock, message: Message
) -> None:
    mocked.get(HTML_CHECK, json=html_check(60))

    with pytest.raises(MailpitAssertionError) as raised:
        message.assert_html_support(at_least=80)

    assert "Worst problems" not in str(raised.value)
