"""What a failed test's report shows about the messages sent to its inboxes.

The terminal report always gets a section with the inbox's messages. When
Allure (``--alluredir``) or pytest-html (``--html``) is in use, the messages
themselves are attached too, so a CI report keeps them after Mailpit is gone.
"""

import html
import re
from dataclasses import dataclass

import pytest

from pytest_mailpit.errors import MailpitError
from pytest_mailpit.inbox import Inbox
from pytest_mailpit.models import Message, MessageSummary
from pytest_mailpit.search import build_query

# How many of an inbox's newest messages are attached; the section lists them all.
MAX_ATTACHED = 10
# What Mailpit allows in a tag: anything else becomes a space.
_NOT_IN_TAGS = re.compile(r"[^a-zA-Z0-9\-_.@ ]+")
MAX_TAG_LENGTH = 100


@dataclass(frozen=True, slots=True)
class _Email:
    message: Message
    source: bytes  # the raw message, as an .eml file holds it


def failure_tag(nodeid: str) -> str:
    """The Mailpit tag of a failed test's messages: "failed" and the test's name.

    "tests/test_shop.py::test_sign_up[en-US]" is tagged "failed test_sign_up en-US".
    """
    words = _NOT_IN_TAGS.sub(" ", nodeid.split("::", 1)[-1]).split()
    return " ".join(["failed", *words])[:MAX_TAG_LENGTH].strip()


def report_failure(
    config: pytest.Config,
    report: pytest.TestReport,
    inboxes: list[Inbox],
    *,
    tag: str | None,
    report_messages: bool,
) -> None:
    """List each inbox's messages once: tag them with ``tag``, and add them to the report."""
    allure = config.pluginmanager.hasplugin("allure_listener")
    pytest_html = bool(config.getoption("htmlpath", None))
    for inbox in inboxes:
        title = f"Mailpit messages to {inbox.address}"
        try:
            found = inbox.messages()
            tagged = tag is not None and found and _add_tag(inbox, found, tag)
            if not report_messages:
                continue
            table = inbox.describe(found)
            emails = []
            if allure or pytest_html:
                for summary in found[-MAX_ATTACHED:]:
                    message = inbox.client.get_message(summary.id)
                    emails.append(_Email(message, inbox.client.get_raw(summary.id)))
        except MailpitError as error:
            if report_messages:
                report.sections.append(
                    (title, f"Could not list the messages to {inbox.address}: {error}")
                )
            continue
        if tagged:
            table += f"\nTagged {tag!r}: {inbox.client.search_url(build_query(tag=tag))}"
        report.sections.append((title, table))
        if allure:
            _attach_to_allure(title, table, emails)
        if pytest_html:
            _add_to_pytest_html(report, inbox, emails)


def _add_tag(inbox: Inbox, found: list[MessageSummary], tag: str) -> bool:
    """Add ``tag`` to the messages, keeping the tags they had; False if Mailpit refused."""
    by_tags: dict[tuple[str, ...], list[str]] = {}
    for summary in found:
        by_tags.setdefault(summary.tags, []).append(summary.id)
    try:
        for tags, ids in by_tags.items():
            inbox.client.set_tags(ids, [*tags, tag])
    except MailpitError:
        return False
    return True


def _attach_to_allure(title: str, table: str, emails: list[_Email]) -> None:
    import allure

    allure.attach(table, name=title, attachment_type=allure.attachment_type.TEXT)
    for email in emails:
        message = email.message
        if message.html:
            allure.attach(
                message.html,
                name=f"Email: {message.subject}",
                attachment_type=allure.attachment_type.HTML,
            )
        else:
            allure.attach(
                message.text,
                name=f"Email: {message.subject}",
                attachment_type=allure.attachment_type.TEXT,
            )
        allure.attach(
            email.source,
            name=f"Email source: {message.subject}",
            attachment_type="message/rfc822",
            extension="eml",
        )


def _add_to_pytest_html(report: pytest.TestReport, inbox: Inbox, emails: list[_Email]) -> None:
    from pytest_html import extras

    report_extras = list(getattr(report, "extras", []))
    for email in emails:
        message = email.message
        report_extras.append(
            # pytest-html puts the name into the report as HTML.
            extras.url(
                inbox.client.view_url(message.id), name=f"Mailpit: {html.escape(message.subject)}"
            )
        )
        report_extras.append(extras.html(_email_card(message)))
    report.extras = report_extras  # type: ignore[attr-defined]


def _email_card(message: Message) -> str:
    """The message for an HTML report: its headers, and the body in a sandboxed frame."""
    recipients = ", ".join(str(address) for address in (*message.to, *message.cc, *message.bcc))
    heading = (
        f"<p><b>{html.escape(message.subject or '(no subject)')}</b><br>"
        f"From {html.escape(str(message.sender))} to {html.escape(recipients or 'no one')}, "
        f"{message.date:%Y-%m-%d %H:%M:%S %Z}</p>"
    )
    if message.html:
        # The frame keeps the email's styles out of the report and runs none of its scripts.
        body = (
            f'<iframe sandbox="" srcdoc="{html.escape(message.html, quote=True)}" '
            'style="width: 100%; height: 400px; border: 1px solid #ccc; background: #fff">'
            "</iframe>"
        )
    else:
        body = f'<pre style="white-space: pre-wrap">{html.escape(message.text)}</pre>'
    return f'<div class="mailpit-message">{heading}{body}</div>'
