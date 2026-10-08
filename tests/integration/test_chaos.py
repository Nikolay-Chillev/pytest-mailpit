"""mailpit_chaos against a real Mailpit, started with MP_ENABLE_CHAOS=true."""

import smtplib

import pytest

from pytest_mailpit import Chaos, ChaosTrigger, ChaosTriggers, Inbox, MailpitClient
from tests.integration.conftest import SendEmail

pytestmark = pytest.mark.integration


def test_rejected_recipients_reach_the_sender(
    mailpit_chaos: Chaos, mailpit_inbox: Inbox, send_email: SendEmail
) -> None:
    mailpit_chaos.reject_recipients(550)

    with pytest.raises(smtplib.SMTPRecipientsRefused) as refused:
        send_email(mailpit_inbox.address)

    assert refused.value.recipients == {mailpit_inbox.address: (550, b"Chaos recipient error")}
    mailpit_inbox.assert_no_message(within=0.5)


def test_a_rejected_sender_can_send_after_a_reset(
    mailpit_chaos: Chaos, mailpit_inbox: Inbox, send_email: SendEmail
) -> None:
    mailpit_chaos.reject_senders()
    with pytest.raises(smtplib.SMTPSenderRefused) as refused:
        send_email(mailpit_inbox.address)
    assert refused.value.smtp_code == 451

    mailpit_chaos.reset()
    send_email(mailpit_inbox.address, subject="Second try")

    assert mailpit_inbox.wait_for_message().subject == "Second try"


def test_the_triggers_are_restored_after_the_test(
    pytester: pytest.Pytester, client: MailpitClient
) -> None:
    pytester.makepyfile(
        "def test_chaos(mailpit_chaos): mailpit_chaos.reject_recipients(probability=50)"
    )

    pytester.runpytest().assert_outcomes(passed=1)

    assert client.chaos() == ChaosTriggers()


def test_set_chaos_applies_every_trigger(client: MailpitClient) -> None:
    triggers = ChaosTriggers(sender=ChaosTrigger(421, 10), authentication=ChaosTrigger(554, 20))
    try:
        assert client.set_chaos(triggers) == triggers
        assert client.chaos() == triggers
    finally:
        client.set_chaos(ChaosTriggers())
