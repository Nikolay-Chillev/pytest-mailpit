"""The client against a real Mailpit, sending real email over SMTP."""

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pytest_mailpit import MailpitAPIError, MailpitClient, build_query
from tests.integration.conftest import SendEmail, arrived

pytestmark = pytest.mark.integration


def test_info_and_readiness(client: MailpitClient) -> None:
    assert client.info().version.startswith("v")
    assert client.is_ready()


def test_search_returns_the_summary_of_a_sent_message(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        subject="Поръчка №1001 е потвърдена",
        cc="accounts@example.test",
        attachment=("invoice.pdf", b"%PDF-1.7 test"),
    )

    [summary] = arrived(client, recipient)

    assert summary.subject == "Поръчка №1001 е потвърдена"
    assert summary.sender.address == "sender@example.test"
    assert summary.sender.name == "Test Sender"
    assert [address.address for address in summary.to] == [recipient]
    assert [address.address for address in summary.cc] == ["accounts@example.test"]
    assert summary.attachments == 1
    assert summary.created.tzinfo is not None


def test_get_message_returns_bodies_and_attachments(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(
        recipient,
        text="Track your order: https://shop.example.test/orders/1001",
        html='<p>Track <a href="https://shop.example.test/orders/1001">your order</a></p>',
        attachment=("invoice.pdf", b"%PDF-1.7 test"),
    )
    [summary] = arrived(client, recipient)

    message = client.get_message(summary.id)

    assert "https://shop.example.test/orders/1001" in message.text
    assert 'href="https://shop.example.test/orders/1001"' in message.html
    [attachment] = message.attachments
    assert attachment.file_name == "invoice.pdf"
    assert client.get_part(message.id, attachment.part_id) == b"%PDF-1.7 test"


def test_get_headers_and_raw_source(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient, subject="Headers check")
    [summary] = arrived(client, recipient)

    assert client.get_headers(summary.id)["Subject"] == ["Headers check"]
    assert b"Subject: Headers check" in client.get_raw(summary.id)


def test_search_all_reads_every_page(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    for number in range(3):
        send_email(recipient, subject=f"Message {number}")
    query = build_query(to=recipient)
    arrived(client, recipient, count=3)

    found = client.search_all(query, page_size=2)

    assert sorted(summary.subject for summary in found) == ["Message 0", "Message 1", "Message 2"]


def test_delete_messages_deletes_only_the_given_ones(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient, subject="Keep")
    send_email(recipient, subject="Delete")
    query = build_query(to=recipient)
    found = arrived(client, recipient, count=2)

    client.delete_messages(summary.id for summary in found if summary.subject == "Delete")

    assert [summary.subject for summary in client.search_all(query)] == ["Keep"]


def test_delete_messages_with_no_ids_keeps_the_mailbox(
    client: MailpitClient, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient)
    query = build_query(to=recipient)
    arrived(client, recipient)

    client.delete_messages([])

    assert len(client.search_all(query)) == 1


def test_delete_search(client: MailpitClient, send_email: SendEmail, recipient: str) -> None:
    send_email(recipient)
    send_email(recipient)
    query = build_query(to=recipient)
    arrived(client, recipient, count=2)

    client.delete_search(query)

    assert client.search_all(query) == []


def test_mark_read_and_unread(client: MailpitClient, send_email: SendEmail, recipient: str) -> None:
    send_email(recipient)
    query = build_query(to=recipient)
    # Waiting fetched the message, so Mailpit has marked it as read.
    [summary] = arrived(client, recipient)

    client.mark_read([summary.id], read=False)
    assert not client.search_all(query)[0].read

    client.mark_read([summary.id])
    assert client.search_all(query)[0].read


def test_unknown_message_is_a_404(client: MailpitClient) -> None:
    with pytest.raises(MailpitAPIError) as raised:
        client.get_message("this-id-does-not-exist")

    assert raised.value.status_code == 404


def test_a_redirect_in_front_of_mailpit_deletes_nothing(
    client: MailpitClient, mailpit_url: str, send_email: SendEmail, recipient: str
) -> None:
    send_email(recipient)
    [message] = arrived(client, recipient)

    class Redirect(BaseHTTPRequestHandler):
        """A proxy that sends every request to Mailpit with a 301, e.g. from http to https."""

        def redirect(self) -> None:
            self.send_response(301)
            self.send_header("Location", mailpit_url + self.path.lstrip("/"))
            self.end_headers()

        do_GET = do_PUT = do_DELETE = redirect

        def log_message(self, *args: object) -> None:
            pass

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        behind_proxy = MailpitClient(f"http://127.0.0.1:{proxy.server_address[1]}/")
        # Following the 301 would have sent DELETE without the IDs: Mailpit deletes everything.
        with pytest.raises(MailpitAPIError, match=f"it redirects to {re.escape(mailpit_url)};"):
            behind_proxy.delete_messages([message.id])
    finally:
        proxy.shutdown()

    assert [summary.id for summary in client.search_all(build_query(to=recipient))] == [message.id]
