from collections.abc import Iterator

import pytest
import responses
from responses import matchers

from pytest_mailpit import MailpitAPIError, MailpitClient, MailpitConnectionError
from tests import samples

URL = "http://mailpit.test:8025/"


@pytest.fixture
def mocked() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as mock:
        yield mock


@pytest.fixture
def client() -> Iterator[MailpitClient]:
    with MailpitClient(URL) as client:
        yield client


# URL and authentication


@pytest.mark.parametrize("url", ["mailpit.test:8025", "ftp://mailpit.test/", "http://"])
def test_rejects_urls_that_are_not_http(url: str) -> None:
    with pytest.raises(ValueError, match="http:// or https://"):
        MailpitClient(url)


@pytest.mark.parametrize("url", ["http://mailpit.test/mailpit", "http://mailpit.test/mailpit/"])
def test_requests_go_under_the_web_root(mocked: responses.RequestsMock, url: str) -> None:
    mocked.get("http://mailpit.test/mailpit/api/v1/info", json=samples.INFO)

    assert MailpitClient(url).info().version == "v1.31.4"


def test_sends_basic_auth(mocked: responses.RequestsMock) -> None:
    mocked.get(
        f"{URL}api/v1/info",
        json=samples.INFO,
        match=[matchers.header_matcher({"Authorization": "Basic dXNlcjpzZWNyZXQ="})],
    )

    MailpitClient(URL, username="user", password="secret").info()


def test_credentials_in_the_url_never_appear_in_api_errors(mocked: responses.RequestsMock) -> None:
    mocked.get("http://user:secret@mailpit.test:8025/api/v1/info", status=401, body="unauthorised")
    client = MailpitClient("http://user:secret@mailpit.test:8025/")

    with pytest.raises(MailpitAPIError) as raised:
        client.info()

    assert client.url == "http://mailpit.test:8025/"
    assert raised.value.url == "http://mailpit.test:8025/api/v1/info"
    assert "secret" not in str(raised.value)


def test_credentials_in_the_url_never_appear_in_connection_errors(
    mocked: responses.RequestsMock,
) -> None:
    # The mock refuses the connection with a message that contains the requested URL.
    client = MailpitClient("http://user:secret@mailpit.test:8025/")

    with pytest.raises(MailpitConnectionError) as raised:
        client.info()

    assert "secret" not in str(raised.value)


def test_credentials_are_removed_from_ipv6_urls() -> None:
    assert MailpitClient("http://user:secret@[::1]:8025/").url == "http://[::1]:8025/"


def test_repr_shows_the_url() -> None:
    assert repr(MailpitClient("http://user:secret@mailpit.test/")) == (
        "MailpitClient('http://mailpit.test/')"
    )


# Reading


def test_search_sends_the_query_and_pagination(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(
        f"{URL}api/v1/search",
        json=samples.MESSAGE_LIST,
        match=[matchers.query_param_matcher({"query": 'to:"a@x.test"', "start": 0, "limit": 50})],
    )

    page = client.search('to:"a@x.test"')

    assert page.messages[0].subject == "Поръчка №1001"


def test_messages_lists_a_page_of_the_mailbox(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(
        f"{URL}api/v1/messages",
        json=samples.MESSAGE_LIST,
        match=[matchers.query_param_matcher({"start": 50, "limit": 25})],
    )

    assert client.messages(start=50, limit=25).total == 12


@pytest.mark.parametrize("query", ["", "  "])
def test_search_rejects_an_empty_query(client: MailpitClient, query: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        client.search(query)


def test_search_all_fetches_every_page_without_duplicates(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    def page(ids: list[str], start: int) -> dict[str, object]:
        return samples.MESSAGE_LIST | {
            "messages_count": 3,
            "start": start,
            "messages": [samples.SUMMARY | {"ID": message_id} for message_id in ids],
        }

    query = "tag:orders"
    # A message arriving between the requests pushes "b" onto the second page as well.
    mocked.get(
        f"{URL}api/v1/search",
        json=page(["a", "b"], 0),
        match=[matchers.query_param_matcher({"query": query, "start": 0, "limit": 2})],
    )
    mocked.get(
        f"{URL}api/v1/search",
        json=page(["b", "c"], 2),
        match=[matchers.query_param_matcher({"query": query, "start": 2, "limit": 2})],
    )

    found = client.search_all(query, page_size=2)

    assert [summary.id for summary in found] == ["a", "b", "c"]


def test_get_message_defaults_to_the_latest(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/message/latest", json=samples.MESSAGE)

    assert client.get_message().attachments[0].file_name == "invoice-1001.pdf"


def test_get_headers_raw_and_part(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.get(f"{URL}api/v1/message/abc/headers", json={"Subject": ["Hello"]})
    mocked.get(f"{URL}api/v1/message/abc/raw", body=b"Subject: Hello\r\n\r\nBody")
    mocked.get(f"{URL}api/v1/message/abc/part/2", body=b"%PDF-1.7")

    assert client.get_headers("abc") == {"Subject": ["Hello"]}
    assert client.get_raw("abc") == b"Subject: Hello\r\n\r\nBody"
    assert client.get_part("abc", "2") == b"%PDF-1.7"


def test_is_ready(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.get(f"{URL}readyz", body="")

    assert client.is_ready()


def test_is_not_ready_while_starting(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.get(f"{URL}readyz", status=503)

    assert not client.is_ready()


# Changing


def test_delete_messages_sends_each_id_once(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.delete(
        f"{URL}api/v1/messages",
        body="ok",
        match=[matchers.json_params_matcher({"IDs": ["a", "b"]})],
    )

    client.delete_messages(["a", "b", "a"])


def test_delete_messages_with_no_ids_sends_nothing(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    # Mailpit deletes the whole mailbox when a delete has no IDs.
    client.delete_messages([])

    assert len(mocked.calls) == 0


def test_delete_messages_rejects_a_single_string(client: MailpitClient) -> None:
    with pytest.raises(TypeError, match="list of message IDs"):
        client.delete_messages("abc")


def test_delete_search(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.delete(
        f"{URL}api/v1/search",
        body="ok",
        match=[matchers.query_param_matcher({"query": "tag:orders"})],
    )

    client.delete_search("tag:orders")


def test_delete_search_rejects_an_empty_query(client: MailpitClient) -> None:
    with pytest.raises(ValueError, match="empty"):
        client.delete_search(" ")


def test_delete_all(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.delete(f"{URL}api/v1/messages", body="ok")

    client.delete_all()


def test_mark_read_and_unread(mocked: responses.RequestsMock, client: MailpitClient) -> None:
    mocked.put(
        f"{URL}api/v1/messages",
        body="ok",
        match=[matchers.json_params_matcher({"IDs": ["a"], "Read": True})],
    )
    mocked.put(
        f"{URL}api/v1/messages",
        body="ok",
        match=[matchers.json_params_matcher({"IDs": ["a"], "Read": False})],
    )

    client.mark_read(["a"])
    client.mark_read(["a"], read=False)


def test_mark_read_with_no_ids_sends_nothing(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    client.mark_read([])

    assert len(mocked.calls) == 0


# Errors


def test_error_status_carries_mailpits_plain_text_message(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/message/missing", status=404, body="message not found\n")

    with pytest.raises(MailpitAPIError) as raised:
        client.get_message("missing")

    assert raised.value.status_code == 404
    assert raised.value.detail == "message not found"
    assert str(raised.value) == (
        f"GET {URL}api/v1/message/missing returned HTTP 404: message not found"
    )


def test_error_status_carries_mailpits_json_error(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/info", status=400, json={"Error": "invalid format"})

    with pytest.raises(MailpitAPIError, match="invalid format"):
        client.info()


def test_json_error_without_an_error_key_is_shown_as_it_is(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/info", status=500, json=["unexpected"])

    with pytest.raises(MailpitAPIError) as raised:
        client.info()

    assert raised.value.detail == '["unexpected"]'


def test_long_error_bodies_are_shortened(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/info", status=500, body="x" * 2000)

    with pytest.raises(MailpitAPIError) as raised:
        client.info()

    assert raised.value.detail.endswith("... (1500 more characters)")


def test_a_page_that_is_not_mailpit_explains_itself(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    mocked.get(f"{URL}api/v1/info", body="<html>Welcome</html>", content_type="text/html")

    with pytest.raises(MailpitAPIError, match=r"expected JSON, got text/html\. Is .* Mailpit\?"):
        client.info()


def test_unreachable_server_raises_a_connection_error(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    # Nothing is registered, so the mock refuses the connection.
    with pytest.raises(MailpitConnectionError, match=f"Cannot reach Mailpit at {URL}"):
        client.info()


def test_unreachable_server_is_not_ready(
    mocked: responses.RequestsMock, client: MailpitClient
) -> None:
    assert not client.is_ready()


def test_view_url_is_the_message_page_in_the_web_ui() -> None:
    client = MailpitClient("http://user:secret@mailpit.test/mailpit")

    assert client.view_url("Aa1Bb2") == "http://mailpit.test/mailpit/view/Aa1Bb2"


# Redirects are never followed


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_delete_is_never_sent_to_where_a_redirect_points(
    client: MailpitClient, status: int
) -> None:
    # After a 301, requests would resend the DELETE without its IDs, and Mailpit would
    # delete every message; after a 302, it would send a GET that changes nothing.
    https = "https://mailpit.test/api/v1/messages"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mocked:
        mocked.delete(f"{URL}api/v1/messages", status=status, headers={"Location": https})
        mocked.delete(https, body="ok")
        mocked.get(https, json=samples.MESSAGE_LIST)

        with pytest.raises(MailpitAPIError) as error:
            client.delete_messages(["m1"])

        assert [call.request.url for call in mocked.calls] == [f"{URL}api/v1/messages"]
    assert error.value.status_code == status
    assert str(error.value) == (
        f"DELETE {URL}api/v1/messages returned HTTP {status}: "
        "it redirects to https://mailpit.test/; point pytest-mailpit at that URL"
    )


def test_reads_are_not_redirected_either(mocked: responses.RequestsMock) -> None:
    client = MailpitClient("http://qa:secret@mailpit.test/mailpit/")
    mocked.get(
        "http://qa:secret@mailpit.test/mailpit/api/v1/messages",
        status=302,
        headers={"Location": "/sso/login?next=/mailpit/api/v1/messages"},
    )

    with pytest.raises(MailpitAPIError) as error:
        client.messages()

    assert str(error.value).endswith(
        "it redirects to http://mailpit.test/sso/login?next=/mailpit/api/v1/messages; "
        "pytest-mailpit needs a URL that answers without redirects"
    )


def test_a_redirect_keeps_credentials_out_of_the_message(mocked: responses.RequestsMock) -> None:
    client = MailpitClient("http://qa:secret@mailpit.test/")
    location = "https://qa:secret@mailpit.test/api/v1/tags"
    mocked.put(
        "http://qa:secret@mailpit.test/api/v1/tags", status=308, headers={"Location": location}
    )

    with pytest.raises(MailpitAPIError) as error:
        client.set_tags(["m1"], ["x"])

    assert "secret" not in str(error.value)
    assert "it redirects to https://mailpit.test/;" in str(error.value)
