"""mailpit_container end to end: an inner session starts a real Mailpit container."""

import pytest

pytestmark = pytest.mark.integration


def test_the_plugin_starts_mailpit_in_a_container(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MAILPIT_URL, which CI sets for the other integration tests, would turn the container off.
    monkeypatch.delenv("MAILPIT_URL", raising=False)
    monkeypatch.delenv("MAILPIT_SMTP", raising=False)
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile(
        """
        import smtplib
        from email.message import EmailMessage
        from urllib.parse import urlsplit

        import pytest


        def send(smtp_server, to, subject):
            message = EmailMessage()
            message["From"] = "app@example.test"
            message["To"] = to
            message["Subject"] = subject
            message.set_content("Hello")
            with smtplib.SMTP(*smtp_server, timeout=10) as smtp:
                smtp.send_message(message)


        def test_email_through_the_container(mailpit_config, mailpit_smtp, mailpit_inbox):
            # Testcontainers publishes the container's ports on random host ports.
            assert urlsplit(mailpit_config.url).port != 8025
            send(mailpit_smtp, mailpit_inbox.address, "From the container")

            assert mailpit_inbox.wait_for_message().subject == "From the container"


        def test_the_container_has_chaos_enabled(mailpit_chaos, mailpit_smtp, mailpit_inbox):
            mailpit_chaos.reject_recipients(550)

            with pytest.raises(smtplib.SMTPRecipientsRefused):
                send(mailpit_smtp, mailpit_inbox.address, "Refused")


        def test_the_container_is_a_plain_mailpit(mailpit_smtp):
            # No STARTTLS with a self-signed certificate; a login that accepts anyone.
            with smtplib.SMTP(*mailpit_smtp, timeout=10) as smtp:
                smtp.ehlo()
                assert not smtp.has_extn("starttls")
                smtp.login("anyone", "any password")
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=3)
    result.stdout.fnmatch_lines(
        ["mailpit: a Docker container of axllent/mailpit, started on first use"]
    )
