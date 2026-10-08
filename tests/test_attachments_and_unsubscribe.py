from typing import Any

import pytest
import responses

from pytest_mailpit import (
    Attachment,
    ListUnsubscribe,
    MailpitAssertionError,
    MailpitClient,
    Message,
)
from tests import samples

URL = "http://mailpit.test:8025/"


def part(file_name: str, content_type: str, size: int = 1234, part_id: str = "2") -> dict[str, Any]:
    return {"PartID": part_id, "FileName": file_name, "ContentType": content_type, "Size": size}


def message(
    attachments: list[dict[str, Any]], inline: list[dict[str, Any]] | None = None
) -> Message:
    return Message.from_api(samples.MESSAGE | {"Attachments": attachments, "Inline": inline or []})


def unsubscribe(
    header: str = "", post: str = "", links: tuple[str, ...] = (), errors: str = ""
) -> Message:
    data = {"Header": header, "HeaderPost": post, "Links": list(links), "Errors": errors}
    return Message.from_api(samples.MESSAGE | {"ListUnsubscribe": data, "Subject": "News"})


# Attachments


def test_attachments_know_their_message() -> None:
    [attachment] = message([part("invoice.pdf", "application/pdf")]).attachments

    assert attachment.message_id == samples.MESSAGE["ID"]


def test_attachment_by_name_type_and_wildcards() -> None:
    email = message(
        [
            part("Invoice-1001.PDF", "application/pdf", part_id="2"),
            part("terms.pdf", "application/pdf", part_id="3"),
            part("logo.png", "image/png; name=logo.png", part_id="4"),
        ]
    )

    assert email.attachment("invoice-*.pdf").part_id == "2"
    assert email.attachment("terms.pdf", content_type="application/pdf").part_id == "3"
    assert email.attachment(content_type="image/*").part_id == "4"
    assert email.attachment(content_type="IMAGE/PNG").part_id == "4"


def test_inline_parts_count_only_when_asked() -> None:
    email = message(
        [part("invoice.pdf", "application/pdf")], inline=[part("logo.png", "image/png")]
    )

    assert email.attachment(content_type="image/png", include_inline=True).file_name == "logo.png"
    with pytest.raises(MailpitAssertionError, match="found 0"):
        email.attachment(content_type="image/png")


def test_attachment_fails_and_lists_the_attachments() -> None:
    email = message(
        [
            part("invoice.pdf", "application/pdf", size=12_345),
            part("terms.txt", "text/plain", size=512),
        ]
    )

    with pytest.raises(MailpitAssertionError) as raised:
        email.attachment("receipt-*.pdf", content_type="application/pdf")

    assert str(raised.value) == (
        "Expected one attachment named 'receipt-*.pdf' and of type 'application/pdf' in message "
        "'Поръчка №1001' to ivan@example.test, found 0.\n"
        "Attachments in the message:\n"
        "  invoice.pdf (application/pdf, 12.3 kB)\n"
        "  terms.txt (text/plain, 512 B)"
    )


def test_attachment_fails_when_several_match() -> None:
    email = message([part("a.pdf", "application/pdf"), part("b.pdf", "application/pdf")])

    with pytest.raises(MailpitAssertionError, match=r"Expected one attachment of type .* found 2"):
        email.attachment(content_type="application/pdf")


def test_attachment_failure_points_at_inline_parts() -> None:
    email = message([], inline=[part("logo.png", "image/png", size=2_500_000)])

    with pytest.raises(MailpitAssertionError) as raised:
        email.attachment()

    assert str(raised.value).endswith(
        "The message has no attachments.\nIt has 1 inline part(s): pass include_inline=True."
    )


def test_get_attachment_downloads_its_content() -> None:
    [invoice] = message([part("invoice.pdf", "application/pdf", part_id="2")]).attachments

    with responses.RequestsMock() as mock:
        mock.get(f"{URL}api/v1/message/{samples.MESSAGE['ID']}/part/2", body=b"%PDF-1.7")
        assert MailpitClient(URL).get_attachment(invoice) == b"%PDF-1.7"


def test_get_attachment_needs_to_know_the_message() -> None:
    orphan = Attachment(part_id="2", file_name="a.pdf", content_type="application/pdf", size=1)

    with pytest.raises(ValueError, match=r"use get_part\(message_id, part_id\)"):
        MailpitClient(URL).get_attachment(orphan)


@pytest.mark.parametrize(
    ("size", "shown"), [(0, "0 B"), (999, "999 B"), (1000, "1.0 kB"), (2_500_000, "2.5 MB")]
)
def test_attachment_sizes_read_well(size: int, shown: str) -> None:
    attachment = Attachment(part_id="2", file_name="", content_type="text/plain", size=size)

    assert str(attachment) == f"(no name) (text/plain, {shown})"


# List-Unsubscribe


def test_list_unsubscribe_links_and_one_click() -> None:
    header = ListUnsubscribe(
        header="<mailto:u@x.test>, <https://x.test/u/1>",
        header_post=" list-unsubscribe=One-Click ",
        links=("mailto:u@x.test", "https://x.test/u/1"),
    )

    assert header.http_link == "https://x.test/u/1"
    assert header.mailto_link == "mailto:u@x.test"
    assert header.one_click
    assert ListUnsubscribe().http_link is ListUnsubscribe().mailto_link is None
    assert not ListUnsubscribe().one_click


def test_unsubscribe_link() -> None:
    email = unsubscribe(
        "<mailto:u@x.test>, <https://x.test/u/1>",
        "List-Unsubscribe=One-Click",
        ("mailto:u@x.test", "https://x.test/u/1"),
    )

    assert email.unsubscribe_link() == "https://x.test/u/1"
    assert email.unsubscribe_link(one_click=True) == "https://x.test/u/1"


def test_unsubscribe_link_without_one_click_may_be_plain_http() -> None:
    email = unsubscribe("<http://x.test/u/1>", links=("http://x.test/u/1",))

    assert email.unsubscribe_link() == "http://x.test/u/1"


@pytest.mark.parametrize(
    ("email", "one_click", "problem"),
    [
        (unsubscribe(), False, "has no List-Unsubscribe header"),
        (
            unsubscribe(
                "https://x.test/u/1", errors='"https://x.test/u/1" should be enclosed in <>'
            ),
            False,
            'has an invalid List-Unsubscribe header: "https://x.test/u/1" should be enclosed in <>',
        ),
        (
            unsubscribe("<mailto:u@x.test>", links=("mailto:u@x.test",)),
            False,
            "has no HTTP(S) link in List-Unsubscribe: <mailto:u@x.test>",
        ),
        (
            unsubscribe(
                "<http://x.test/u/1>", "List-Unsubscribe=One-Click", ("http://x.test/u/1",)
            ),
            True,
            "has a one-click unsubscribe link that is not HTTPS: http://x.test/u/1",
        ),
        (
            unsubscribe("<https://x.test/u/1>", links=("https://x.test/u/1",)),
            True,
            "does not offer one-click unsubscription: List-Unsubscribe-Post should be "
            "'List-Unsubscribe=One-Click', got 'missing'",
        ),
    ],
)
def test_unsubscribe_link_failures(email: Message, one_click: bool, problem: str) -> None:
    with pytest.raises(MailpitAssertionError) as raised:
        email.unsubscribe_link(one_click=one_click)

    assert str(raised.value) == f"The message 'News' to ivan@example.test {problem}."


def test_attachment_failure_on_a_message_without_any_parts() -> None:
    with pytest.raises(MailpitAssertionError) as raised:
        message([]).attachment("invoice.pdf")

    assert str(raised.value).endswith("found 0.\nThe message has no attachments.")
