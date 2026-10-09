"""Tags: a failed test's kept messages are tagged with its name, to find them in Mailpit."""

import json
import re
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from requests import PreparedRequest

from pytest_mailpit import MailpitClient
from pytest_mailpit._reporting import MAX_TAG_LENGTH, failure_tag
from pytest_mailpit.inbox import nodeid_hash
from tests.test_waiting import page, summary

URL = "http://localhost:8025/"
SEARCH = re.compile(re.escape(f"{URL}api/v1/search") + r"\?.*")
TAGS = f"{URL}api/v1/tags"
FAILING = "def test_fails(mailpit_inbox): assert False"


@pytest.mark.parametrize(
    ("nodeid", "name"),
    [
        ("tests/test_shop.py::test_sign_up", "test_sign_up"),
        ("tests/test_shop.py::TestCart::test_total[en-US/2]", "TestCart test_total en-US 2"),
        # Mailpit's tags hold only ASCII, and "@" not before 1.28.3.
        ("test_вход.py::test_вход[ivan@example.com]", "test_ ivan example.com"),
    ],
)
def test_the_tag_names_the_test_as_mailpit_allows(nodeid: str, name: str) -> None:
    assert failure_tag(nodeid) == f"failed {nodeid_hash(nodeid)} {name}"
    assert re.fullmatch(r"[a-zA-Z0-9\-_. ]{1,100}", failure_tag(nodeid))


def test_a_long_name_is_cut_to_what_mailpit_keeps() -> None:
    assert len(failure_tag("t.py::test_" + "x" * 200)) == MAX_TAG_LENGTH


def test_tests_that_share_a_name_get_different_tags() -> None:
    # The same name in two files, or two names in another alphabet.
    assert failure_tag("tests/api/test_users.py::test_create") != failure_tag(
        "tests/ui/test_users.py::test_create"
    )
    assert failure_tag("t.py::test_вход") != failure_tag("t.py::test_изход")


def test_set_tags_replaces_the_tags_of_the_messages() -> None:
    client = MailpitClient(URL)
    with responses.RequestsMock() as mock:
        mock.put(TAGS, body="ok")

        client.set_tags(["m1", "m2", "m1"], ["orders", "failed test_x"])
        client.set_tags([], ["ignored"])

        assert len(mock.calls) == 1
        assert json.loads(mock.calls[0].request.body or "{}") == {
            "IDs": ["m1", "m2"],
            "Tags": ["orders", "failed test_x"],
        }


def test_search_url() -> None:
    client = MailpitClient("http://user:secret@mailpit.test:8025/mailpit/")

    assert client.search_url('tag:"failed test_x"') == (
        "http://mailpit.test:8025/mailpit/search?q=tag%3A%22failed%20test_x%22"
    )
    with pytest.raises(ValueError, match="query"):
        client.search_url(" ")


# The plugin, in inner sessions


@pytest.fixture
def server() -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit at the default URL, holding one message, tagged "orders", per inbox."""

    def one_per_address(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        query = parse_qs(urlsplit(request.url or "").query)["query"][0]
        address = re.search(r'addressed:"([^"]+)"', query)
        found = [summary("m1", to=address.group(1))] if address else []
        return 200, {}, json.dumps(page(*found))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/messages", json=page())
        mock.add_callback(responses.GET, SEARCH, callback=one_per_address)
        mock.delete(f"{URL}api/v1/messages", body="ok")
        mock.put(TAGS, body="ok")
        yield mock


def tagged(server: responses.RequestsMock) -> list[object]:
    return [
        json.loads(call.request.body or "{}") for call in server.calls if call.request.url == TAGS
    ]


# The hash of the inner session's test, test_fails in a file named after the outer test.
HASH = nodeid_hash(
    "test_a_failed_tests_messages_are_tagged_and_the_report_links_to_them.py::test_fails"
)


def test_a_failed_tests_messages_are_tagged_and_the_report_links_to_them(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(FAILING)

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    # The tag the application gave the message stays.
    [call] = tagged(server)
    assert call == {"IDs": ["m1"], "Tags": ["orders", f"failed {HASH} test_fails"]}
    result.stdout.fnmatch_lines(
        [
            "*Mailpit messages to pytest-*",
            "Mailpit: http://localhost:8025/",
            f"Tagged 'failed {HASH} test_fails': "
            f"http://localhost:8025/search?q=tag%3A%22failed%20{HASH}%20test_fails%22",
        ]
    )


@pytest.mark.parametrize(
    ("ini", "tests"),
    [
        ("mailpit_tag_failures = false", FAILING),
        ("mailpit_keep_on_failure = false", FAILING),
        ("", "def test_passes(mailpit_inbox): pass"),
    ],
    ids=["turned off", "messages deleted", "test passed"],
)
def test_no_tags_unless_a_failed_test_keeps_its_messages(
    pytester: pytest.Pytester, server: responses.RequestsMock, ini: str, tests: str
) -> None:
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile(tests)

    result = pytester.runpytest()

    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) + outcomes.get("failed", 0) == 1
    assert tagged(server) == []
    assert "Tagged" not in result.stdout.str()


def test_tags_without_reports(pytester: pytest.Pytester, server: responses.RequestsMock) -> None:
    pytester.makeini("[pytest]\nmailpit_report_messages = false\n")
    pytester.makepyfile(FAILING)

    result = pytester.runpytest()

    assert len(tagged(server)) == 1
    assert "Mailpit messages to" not in result.stdout.str()


def test_mailpit_failing_while_tagging_without_reports_is_quiet(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    server.replace(responses.GET, SEARCH, status=500, body="database is locked")
    pytester.makeini("[pytest]\nmailpit_report_messages = false\n")
    pytester.makepyfile(FAILING)

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    assert tagged(server) == []
    assert "Could not list" not in result.stdout.str()


def test_no_tags_and_no_reports_ask_mailpit_nothing(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makeini("[pytest]\nmailpit_report_messages = false\nmailpit_tag_failures = false\n")
    pytester.makepyfile(FAILING)

    pytester.runpytest().assert_outcomes(failed=1)

    assert not [call for call in server.calls if SEARCH.match(call.request.url or "")]


def test_a_failed_tag_leaves_the_report_without_the_link(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    server.replace(responses.PUT, TAGS, status=500, body="database is locked")
    pytester.makepyfile(FAILING)

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["Mailpit: http://localhost:8025/"])
    assert "Tagged" not in result.stdout.str()


def test_an_empty_inbox_is_not_tagged(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    server.replace(responses.GET, SEARCH, json=page())
    pytester.makepyfile(FAILING)

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    assert tagged(server) == []
    result.stdout.fnmatch_lines(["No messages to pytest-*"])
