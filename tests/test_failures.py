"""Which failures keep a test's messages: in its setup, call or teardown, reruns and interrupts."""

import json
import re
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from requests import PreparedRequest

from tests import samples
from tests.test_waiting import page, summary

URL = "http://localhost:8025/"
SEARCH = re.compile(re.escape(f"{URL}api/v1/search") + r"\?.*")


def one_per_address(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
    query = parse_qs(urlsplit(request.url or "").query)["query"][0]
    address = re.search(r'addressed:"([^"]+)"', query)
    found = [summary(f"id-{address.group(1)}", to=address.group(1))] if address else []
    return 200, {}, json.dumps(page(*found))


@pytest.fixture
def server() -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit at the default URL, holding one message for every inbox."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/messages", json=samples.MESSAGE_LIST)
        mock.add_callback(responses.GET, SEARCH, callback=one_per_address)
        mock.delete(f"{URL}api/v1/messages", body="ok")
        mock.put(f"{URL}api/v1/tags", body="ok")
        yield mock


def deleted(server: responses.RequestsMock) -> list[str]:
    deletes = [call for call in server.calls if call.request.method == "DELETE"]
    return [i for call in deletes for i in json.loads(call.request.body or "{}")["IDs"]]


def test_a_fixture_that_fails_in_its_setup_keeps_and_reports_the_messages(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def confirmed_user(mailpit_inbox):
            assert False, "the confirmation email never came"

        def test_profile(confirmed_user):
            pass
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    assert deleted(server) == []
    result.stdout.fnmatch_lines(
        ["*Mailpit messages to pytest-*", "Tagged 'failed ?????? test_profile': *"]
    )


def test_a_fixture_that_fails_in_its_teardown_keeps_and_reports_the_messages(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def checked_inbox(mailpit_inbox):
            yield mailpit_inbox
            assert False, "an error report email arrived too"

        def test_order(checked_inbox):
            pass
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1, errors=1)
    assert deleted(server) == []
    result.stdout.fnmatch_lines(["*Mailpit messages to pytest-*"])


def test_an_interrupted_run_keeps_the_messages(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile("def test_stopped(mailpit_inbox): raise KeyboardInterrupt")

    run = pytester.inline_run(no_reraise_ctrlc=True)

    assert run.ret == pytest.ExitCode.INTERRUPTED
    assert deleted(server) == []


RERUN = """
import pytest
from _pytest.runner import runtestprotocol


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    # Runs a failed test once more, as pytest-rerunfailures does.
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    reports = runtestprotocol(item, nextitem=nextitem, log=False)
    if any(report.failed for report in reports):
        reports = runtestprotocol(item, nextitem=nextitem, log=False)
    for report in reports:
        item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
"""


def test_a_rerun_starts_afresh(pytester: pytest.Pytester, server: responses.RequestsMock) -> None:
    pytester.makeconftest(RERUN)
    pytester.makepyfile(
        """
        addresses = []

        def test_flaky(mailpit_inbox):
            addresses.append(mailpit_inbox.address)
            assert len(addresses) == 2, "fails the first time"
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    # The failed attempt kept its message; the passing one deleted only its own.
    [deleted_id] = deleted(server)
    tagged = [call for call in server.calls if call.request.method == "PUT"]
    [kept_id] = json.loads(tagged[0].request.body or "{}")["IDs"]
    assert deleted_id != kept_id


@pytest.mark.parametrize(("tests", "warnings"), [(1, 0), (2, 1)])
def test_mailpit_gone_at_the_end_of_the_session_is_no_warning(
    pytester: pytest.Pytester, tests: int, warnings: int
) -> None:
    # Mailpit refuses every DELETE, as if it went away, e.g. its container at the end.
    pytester.makepyfile("\n".join(f"def test_{n}(mailpit_inbox): pass" for n in range(tests)))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/messages", json=samples.MESSAGE_LIST)
        mock.add_callback(responses.GET, SEARCH, callback=one_per_address)
        result = pytester.runpytest()

    result.assert_outcomes(passed=tests, warnings=warnings)
