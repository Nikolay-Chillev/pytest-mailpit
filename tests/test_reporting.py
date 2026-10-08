"""A failed test's messages in Allure and pytest-html reports, run in inner sessions."""

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from requests import PreparedRequest

from pytest_mailpit import Message
from pytest_mailpit._reporting import _email_card
from tests import samples
from tests.test_plugin import MESSAGE, SEARCH, URL
from tests.test_waiting import page, summary

RAW = re.compile(re.escape(f"{URL}api/v1/message/") + r"[^/]+/raw$")
SOURCE = b"From: shop@example.test\r\nSubject: Order\r\n\r\nThank you for your order."
FAILING_TEST = "def test_fails(mailpit_inbox):\n    assert False\n"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MAILPIT_URL", "MAILPIT_WAIT_TIMEOUT", "PYTEST_XDIST_WORKER"):
        monkeypatch.delenv(name, raising=False)


def mailpit_with(
    messages_per_inbox: int = 1, html_part: str | None = None
) -> responses.RequestsMock:
    """A mocked Mailpit where every inbox has ``messages_per_inbox`` messages."""

    def search(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        query = parse_qs(urlsplit(request.url or "").query)["query"][0]
        address = re.search(r'addressed:"([^"]+)"', query)
        found = []
        if address:
            found = [
                summary(f"m{n}", to=address.group(1), created=f"2026-10-08T09:00:{n:02}Z")
                for n in range(messages_per_inbox, 0, -1)
            ]
        return 200, {"Content-Type": "application/json"}, json.dumps(page(*found))

    def message(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        data = samples.MESSAGE | {"ID": (request.url or "").rsplit("/", 1)[1]}
        if html_part is not None:
            data["HTML"] = html_part
        return 200, {"Content-Type": "application/json"}, json.dumps(data)

    mock = responses.RequestsMock(assert_all_requests_are_fired=False)
    mock.get(f"{URL}api/v1/info", json=samples.INFO)
    mock.add_callback(responses.GET, SEARCH, callback=search)
    mock.get(RAW, body=SOURCE)
    mock.add_callback(responses.GET, MESSAGE, callback=message)
    return mock


def allure_attachments(directory: Path) -> list[dict[str, Any]]:
    [result] = [json.loads(path.read_text("utf-8")) for path in directory.glob("*-result.json")]
    attachments: list[dict[str, Any]] = result.get("attachments", [])
    for attachment in attachments:
        attachment["content"] = (directory / attachment["source"]).read_bytes()
    return attachments


def pytest_html_extras(report: Path) -> list[dict[str, Any]]:
    blob = re.search(r'data-jsonblob="([^"]*)"', report.read_text("utf-8"))
    assert blob, "no data in the pytest-html report"
    data = json.loads(html.unescape(blob.group(1)))
    [results] = data["tests"].values()
    return [extra for result in results for extra in result.get("extras", [])]


def requested(mock: responses.RequestsMock, pattern: re.Pattern[str]) -> int:
    return len([call for call in mock.calls if pattern.match(call.request.url or "")])


# Allure


def test_allure_gets_the_table_the_email_and_its_source(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with():
        pytester.runpytest("--alluredir=allure-results").assert_outcomes(failed=1)

    attachments = allure_attachments(pytester.path / "allure-results")
    assert [(a["name"].split(" pytest-")[0], a["type"]) for a in attachments] == [
        ("Mailpit messages to", "text/plain"),
        ("Email: Поръчка №1001", "text/html"),
        ("Email source: Поръчка №1001", "message/rfc822"),
    ]
    table, body, source = (a["content"] for a in attachments)
    assert b"Received (UTC)" in table
    assert body.decode() == samples.MESSAGE["HTML"]
    assert source == SOURCE
    assert attachments[2]["source"].endswith(".eml")


def test_allure_gets_the_text_of_an_email_without_html(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with(html_part=""):
        pytester.runpytest("--alluredir=allure-results").assert_outcomes(failed=1)

    body = allure_attachments(pytester.path / "allure-results")[1]
    assert body["type"] == "text/plain"
    assert body["content"].decode() == samples.MESSAGE["Text"]


def test_at_most_the_ten_newest_emails_are_attached(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with(messages_per_inbox=12) as mock:
        pytester.runpytest("--alluredir=allure-results").assert_outcomes(failed=1)
        # responses forgets the calls when the block ends.
        assert requested(mock, RAW) == 10

    attachments = allure_attachments(pytester.path / "allure-results")
    assert len(attachments) == 1 + 10 * 2
    sources = [a["name"] for a in attachments if a["type"] == "message/rfc822"]
    assert len(sources) == 10


def test_a_passing_test_attaches_nothing(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("def test_passes(mailpit_inbox):\n    pass\n")

    with mailpit_with() as mock:
        mock.delete(f"{URL}api/v1/messages", body="ok")
        pytester.runpytest("--alluredir=allure-results").assert_outcomes(passed=1)

    assert allure_attachments(pytester.path / "allure-results") == []


# pytest-html


def test_pytest_html_gets_a_link_to_mailpit_and_the_email(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with():
        pytester.runpytest("--html=report.html", "--self-contained-html").assert_outcomes(failed=1)

    extras = pytest_html_extras(pytester.path / "report.html")
    links = [extra for extra in extras if extra["format_type"] == "url"]
    cards = [extra for extra in extras if extra["format_type"] == "html"]
    assert [link["name"] for link in links] == ["Mailpit: Поръчка №1001"]
    assert links[0]["content"] == f"{URL}view/m1"
    [card] = cards
    assert (
        '<iframe sandbox="" srcdoc="&lt;p&gt;Thank you for your order.&lt;/p&gt;' in card["content"]
    )


# What is not done


def test_without_allure_or_pytest_html_no_email_is_fetched(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with() as mock:
        result = pytester.runpytest()
        assert requested(mock, SEARCH) == 1
        assert requested(mock, MESSAGE) == requested(mock, RAW) == 0

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*Mailpit messages to pytest-*"])


def test_reporting_messages_can_be_turned_off(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmailpit_report_messages = false\n")
    pytester.makepyfile(FAILING_TEST)

    with mailpit_with() as mock:
        result = pytester.runpytest("--alluredir=allure-results")
        # The messages are listed to tag them, but never fetched.
        assert requested(mock, MESSAGE) == requested(mock, RAW) == 0

    result.assert_outcomes(failed=1)
    assert "Mailpit messages to" not in result.stdout.str()
    assert allure_attachments(pytester.path / "allure-results") == []


def test_mailpit_going_away_leaves_a_note_and_no_attachments(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FAILING_TEST)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        result = pytester.runpytest("--alluredir=allure-results")

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["Could not list the messages to pytest-*: Cannot reach Mailpit*"])
    assert allure_attachments(pytester.path / "allure-results") == []


# The email card of the HTML report


def test_email_card_escapes_everything_from_the_email() -> None:
    message = Message.from_api(
        samples.MESSAGE | {"Subject": "<script>alert(1)</script>", "HTML": '<p onclick="x">Hi</p>'}
    )

    card = _email_card(message)

    assert "<script>" not in card
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in card
    assert 'srcdoc="&lt;p onclick=&quot;x&quot;&gt;Hi&lt;/p&gt;"' in card
    assert "From Shop <orders@shop.example.test>" not in card  # angle brackets are escaped
    assert (
        "From Shop &lt;orders@shop.example.test&gt; to Ivan Petrov &lt;ivan@example.test&gt;"
        in card
    )


def test_email_card_shows_the_text_of_an_email_without_html() -> None:
    message = Message.from_api(samples.MESSAGE | {"HTML": "", "Text": "Hello <friend>"})

    card = _email_card(message)

    assert '<pre style="white-space: pre-wrap">Hello &lt;friend&gt;</pre>' in card
    assert "<iframe" not in card
