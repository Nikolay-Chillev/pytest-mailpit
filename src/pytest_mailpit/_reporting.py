"""What a failed test's report shows about the messages sent to its inboxes.

The terminal report always gets a section with the inbox's messages. When
Allure (``--alluredir``) or pytest-html (``--html``) is in use, the messages
themselves are attached too, so a CI report keeps them after Mailpit is gone.
"""

import html
from dataclasses import dataclass

import pytest

from pytest_mailpit.errors import MailpitError
from pytest_mailpit.inbox import Inbox
from pytest_mailpit.models import Message

# How many of an inbox's newest messages are attached; the section lists them all.
MAX_ATTACHED = 10


@dataclass(frozen=True, slots=True)
class _Email:
    message: Message
    source: bytes  # the raw message, as an .eml file holds it


def report_failure(config: pytest.Config, report: pytest.TestReport, inboxes: list[Inbox]) -> None:
    allure = config.pluginmanager.hasplugin("allure_listener")
    pytest_html = bool(config.getoption("htmlpath", None))
    for inbox in inboxes:
        title = f"Mailpit messages to {inbox.address}"
        try:
            found = inbox.messages()
            table = inbox.describe(found)
            emails = []
            if allure or pytest_html:
                for summary in found[-MAX_ATTACHED:]:
                    message = inbox.client.get_message(summary.id)
                    emails.append(_Email(message, inbox.client.get_raw(summary.id)))
        except MailpitError as error:
            report.sections.append(
                (title, f"Could not list the messages to {inbox.address}: {error}")
            )
            continue
        report.sections.append((title, table))
        if allure:
            _attach_to_allure(title, table, emails)
        if pytest_html:
            _add_to_pytest_html(report, inbox, emails)


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
            extras.url(inbox.client.view_url(message.id), name=f"Mailpit: {message.subject}")
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
