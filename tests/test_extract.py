import re

import pytest

from pytest_mailpit import MailpitAssertionError, Message
from pytest_mailpit.extract import html_to_text
from tests import samples


def message(*, text: str = "", html: str = "", subject: str = "Hello") -> Message:
    return Message.from_api(samples.MESSAGE | {"Text": text, "HTML": html, "Subject": subject})


# Links


def test_links_come_from_the_html_and_the_text_once_each() -> None:
    email = message(
        html='<a href="https://shop.test/orders/1">Track</a> <a href="https://shop.test/help">Help</a>',
        text="Track: https://shop.test/orders/1\nUnsubscribe: https://shop.test/u/9",
    )

    assert email.links() == [
        "https://shop.test/orders/1",
        "https://shop.test/help",
        "https://shop.test/u/9",
    ]


def test_html_entities_in_href_are_decoded() -> None:
    email = message(html='<a href="https://shop.test/reset?token=abc&amp;user=7">Reset</a>')

    assert email.links() == ["https://shop.test/reset?token=abc&user=7"]


def test_sentence_punctuation_after_a_url_in_text_is_dropped() -> None:
    email = message(text="Open https://shop.test/reset/abc. Or (https://shop.test/help), thanks!")

    assert email.links() == ["https://shop.test/reset/abc", "https://shop.test/help"]


def test_only_http_links_count() -> None:
    email = message(
        html='<a href="mailto:help@shop.test">Mail</a><a href="tel:+359">Call</a>'
        '<a href="#top">Top</a><a>No href</a><a href="https://shop.test/">Site</a>'
    )

    assert email.links() == ["https://shop.test/"]


def test_links_filtered_by_url_pattern_and_visible_text() -> None:
    email = message(
        html='<a href="https://shop.test/reset/abc">Reset your password</a>'
        '<a href="https://shop.test/orders/1">Track your order</a>'
        '<area href="https://shop.test/map" alt="Map">'
    )

    assert email.links("/orders/") == ["https://shop.test/orders/1"]
    assert email.links(pattern=r"/reset/\w+$") == ["https://shop.test/reset/abc"]
    assert email.links(pattern=re.compile("MAP", re.IGNORECASE)) == ["https://shop.test/map"]
    assert email.links(text="RESET") == ["https://shop.test/reset/abc"]
    assert email.links("shop.test", text="your") == [
        "https://shop.test/reset/abc",
        "https://shop.test/orders/1",
    ]


def test_link_text_spans_nested_tags_and_unclosed_anchors() -> None:
    email = message(
        html='<a href="https://a.test/1"><b>Confirm</b>\n  <i>email</i></a>'
        '<a href="https://a.test/2">Open<a href="https://a.test/3">Last'
    )

    assert email.links(text="confirm email") == ["https://a.test/1"]
    assert email.links(text="open") == ["https://a.test/2"]
    assert email.links(text="last") == ["https://a.test/3"]


def test_link_returns_the_only_match() -> None:
    email = message(html='<a href="https://shop.test/reset/abc">Reset</a>')

    assert email.link("/reset/") == "https://shop.test/reset/abc"


def test_link_fails_and_lists_the_links_when_none_matches() -> None:
    email = message(
        html='<a href="https://shop.test/orders/1">Track</a>',
        text="Help: https://shop.test/help",
        subject="Order shipped",
    )

    with pytest.raises(MailpitAssertionError) as raised:
        email.link("/reset/", text="Reset")

    assert str(raised.value) == (
        "Expected one link containing '/reset/' and with text 'Reset' in message "
        "'Order shipped' to ivan@example.test, found 0.\n"
        "Links in the message:\n"
        "  https://shop.test/orders/1  (text: 'Track')\n"
        "  https://shop.test/help"
    )


def test_link_fails_when_several_match() -> None:
    email = message(text="https://a.test/1 https://a.test/2")

    with pytest.raises(MailpitAssertionError, match="found 2"):
        email.link(pattern="a.test")


def test_link_failure_says_when_there_are_no_links() -> None:
    with pytest.raises(MailpitAssertionError, match="The message has no http\\(s\\) links"):
        message(text="No links here").link()


# Codes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your verification code is 482913.", ["482913"]),
        ("Use 4829 as your one-time password", ["4829"]),
        ("OTP: 123-456", ["123456"]),
        ("Your code: 123 456", ["123456"]),
        ("Вашият код за потвърждение е 77421.", ["77421"]),
        ("Кодът за вход: 5512", ["5512"]),
    ],
)
def test_codes_next_to_keywords(text: str, expected: list[str]) -> None:
    assert message(text=text).codes() == expected


def test_dates_times_amounts_phones_and_urls_are_not_codes() -> None:
    text = (
        "Order 2026-10-07 at 14:30 for 1,250.00 BGN, call +359 2 123 4567. "
        "Details: https://shop.test/orders/882211"
    )

    assert message(text=text).codes() == []


def test_codes_near_a_keyword_win_over_other_numbers() -> None:
    text = (
        "Order number 55821 was placed. "
        + "Thank you for shopping with us. " * 4
        + "Your code: 9134"
    )

    assert message(text=text).codes() == ["9134"]


def test_codes_without_keywords_are_returned_in_order() -> None:
    assert message(text="Numbers 1111 and 2222").codes() == ["1111", "2222"]


def test_codes_are_read_from_the_html_when_there_is_no_text_part() -> None:
    html = "<style>.x{width:9999px}</style><p>Your code is</p><p><b>4471</b></p>"

    assert message(html=html).codes() == ["4471"]


def test_codes_with_a_custom_pattern() -> None:
    email = message(text="Token: AB-12-CD, backup AB-34-EF")

    assert email.codes(r"[A-Z]{2}-\d{2}-[A-Z]{2}") == ["AB-12-CD", "AB-34-EF"]
    assert email.codes(r"backup ([A-Z0-9-]+)") == ["AB-34-EF"]


def test_code_returns_the_only_one() -> None:
    assert message(text="Your code is 482913").code() == "482913"


def test_code_fails_with_the_candidates_when_ambiguous() -> None:
    email = message(text="Code 1111 or code 2222", subject="Sign in")

    with pytest.raises(MailpitAssertionError) as raised:
        email.code()

    assert str(raised.value) == (
        "Expected one one-time code in message 'Sign in' to ivan@example.test, found 2: "
        "1111, 2222.\nPass pattern= to say which one is the code."
    )


def test_code_fails_with_an_excerpt_when_there_is_none() -> None:
    email = message(text="Welcome aboard!\n\nNo code today.", subject="Welcome")

    with pytest.raises(MailpitAssertionError) as raised:
        email.code(r"\d{6}")

    assert str(raised.value) == (
        "Expected one code matching '\\\\d{6}' in message 'Welcome' to ivan@example.test, "
        "found 0.\nText of the message: 'Welcome aboard! No code today.'"
    )


def test_code_failure_shortens_long_messages() -> None:
    with pytest.raises(MailpitAssertionError, match=r"\.\.\.'$"):
        message(text="word " * 200).code()


def test_html_to_text_skips_head_scripts_and_styles() -> None:
    html = (
        "<html><head><title>T</title><style>p{}</style></head>"
        "<body><p>Hello</p><script>var x=1</script><p>world</p></body></html>"
    )

    assert html_to_text(html) == "Hello\nworld"


def test_code_with_a_pattern_does_not_suggest_one_when_ambiguous() -> None:
    with pytest.raises(MailpitAssertionError) as raised:
        message(text="A-1 and A-2").code(r"A-\d")

    assert str(raised.value).endswith("found 2: A-1, A-2.")


# Real emails: what the heuristics see besides the code

OTP_TEXT = """Hi Ivan,

Your verification code is: 482913

This code will expire in 10 minutes. If you did not request this code, ignore this email.

(c) 2026 Acme Ltd. · 1 Main St, Springfield, IL 62704 · (800) 555-0199
"""

OTP_HTML = """<!doctype html><html><head><title>Your code</title>
<style>.code{font-size:32px}</style></head><body><table><tr><td>
<h1>Confirm your email</h1><p>Your verification code</p><p class="code">482913</p>
<p>15 minutes until it expires. If you didn't request this code, ignore this email.</p>
</td></tr><tr><td>&copy; 2026 Acme Ltd. &middot; 15 Vitosha Blvd, 1000 Sofia</td></tr>
</table></body></html>"""


@pytest.mark.parametrize(
    ("text", "html"), [(OTP_TEXT, OTP_HTML), ("", OTP_HTML)], ids=["text part", "HTML only"]
)
def test_a_real_otp_email_has_one_code(text: str, html: str) -> None:
    assert message(text=text, html=html).code() == "482913"


@pytest.mark.parametrize(
    "text",
    [
        "Your code 482913 expires in 1440 minutes.",
        "Your code: 482913. Total: $1299, or 1500 лв.",
        "Reference: 77812345. Your verification code: 482913.",
        "Order #10023: your code is 482913",
        "Your code is 482913, sent on October 7, 2026.",
        "Кодът ви е 482913, изпратен на 7 октомври 2026 г.",
        "Your code is 482913. Questions? Call (800) 555-0199.",
    ],
)
def test_numbers_next_to_the_code_that_are_not_codes(text: str) -> None:
    assert message(text=text).codes() == ["482913"]


def test_a_year_is_a_code_when_there_is_nothing_else() -> None:
    assert message(text="Your PIN is 2026").codes() == ["2026"]


def test_codes_in_the_html_when_the_text_part_has_none() -> None:
    email = message(
        text="This email needs an HTML client.",
        html="<p>Your code:</p><p>482913</p>",
    )

    assert email.code() == "482913"


def test_html_after_an_unclosed_head_is_read() -> None:
    html = "<html><head><title>Code</title><body><p>Your code is 4829</p></body></html>"

    assert message(html=html).codes() == ["4829"]


def test_a_pattern_group_that_takes_no_part_is_skipped() -> None:
    email = message(text="Code: 4829. Backup: none")

    assert email.codes(r"Code: (\d+)|Backup: (\w+)") == ["4829"]


# Real emails: links


def test_a_url_keeps_every_text_it_has() -> None:
    # A logo, then a button to the same page.
    email = message(
        html='<a href="https://shop.test/reset/abc"><img src="logo.png" alt=""></a>'
        '<a href="https://shop.test/reset/abc">Reset your password</a>'
    )

    assert email.link(text="Reset your password") == "https://shop.test/reset/abc"


def test_an_image_alt_text_is_the_text_of_its_link() -> None:
    email = message(html='<a href="https://shop.test/confirm"><img alt="Confirm"></a>')

    assert email.link(text="confirm") == "https://shop.test/confirm"


def test_a_failure_lists_every_text_of_a_link() -> None:
    email = message(
        html='<a href="https://shop.test/">Shop</a><a href="https://shop.test/">Home</a>'
    )

    with pytest.raises(MailpitAssertionError) as raised:
        email.link(text="Reset")

    assert str(raised.value).endswith("  https://shop.test/  (text: 'Shop', 'Home')")


def test_a_placeholder_host_is_not_a_link() -> None:
    email = message(
        html='<a href="https://[unsubscribe_url]">Out</a><a href="https://a.test/">A</a>'
    )

    assert email.links() == ["https://a.test/"]


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("Отворете „https://app.test/confirm/abc“.", "https://app.test/confirm/abc"),
        ("Link: «https://app.test/confirm/abc»", "https://app.test/confirm/abc"),
        ("See https://app.test/wiki/Foo_(bar).", "https://app.test/wiki/Foo_(bar)"),
        ("Reset: https://app.test/reset/abc​", "https://app.test/reset/abc"),
    ],
)
def test_urls_in_text_end_where_the_sentence_goes_on(text: str, url: str) -> None:
    assert message(text=text).links() == [url]


def test_a_number_far_from_the_keyword_on_its_line_is_not_a_code() -> None:
    text = "Welcome 55821. " + "Thank you for shopping with us. " * 3 + "Your code: 9134"

    assert message(text=text).codes() == ["9134"]


def test_a_code_on_its_own_line_far_below_the_keyword_is_found_by_distance() -> None:
    text = "Your code\nis below.\nKeep it safe.\nDo not share it.\n4829"

    assert message(text=text).codes() == ["4829"]


def test_a_pattern_finds_a_token_inside_a_link() -> None:
    email = message(text="Sign in: https://shop.test/magic?token=Xy12AbC9")

    assert email.code(r"token=(\w+)") == "Xy12AbC9"


@pytest.mark.parametrize(
    ("fields", "described"),
    [
        ({"Cc": [{"Name": "", "Address": "pytest-a@example.com"}]}, "to cc pytest-a@example.com"),
        ({"Bcc": [{"Name": "", "Address": "pytest-a@example.com"}]}, "to bcc pytest-a@example.com"),
        ({}, "to no one"),
    ],
)
def test_a_failure_names_the_cc_or_bcc_of_a_message_without_to(
    fields: dict[str, object], described: str
) -> None:
    # A newsletter to "undisclosed-recipients", its readers in Bcc.
    email = Message.from_api(samples.MESSAGE | {"To": [], "Cc": [], "Bcc": []} | fields)

    with pytest.raises(MailpitAssertionError, match=f"in message .* {described}, found 0"):
        email.link("/no-such-link/")
