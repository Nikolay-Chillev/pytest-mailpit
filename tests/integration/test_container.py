"""mailpit_container end to end: an inner session starts a real Mailpit container."""

import pytest

pytestmark = pytest.mark.integration


def test_the_plugin_starts_mailpit_in_a_container(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmailpit_container = true\n")
    pytester.makepyfile(
        """
        import smtplib
        from email.message import EmailMessage
        from urllib.parse import urlsplit


        def test_email_through_the_container(mailpit_config, mailpit_smtp, mailpit_inbox):
            # Testcontainers publishes the container's ports on random host ports.
            assert urlsplit(mailpit_config.url).port != 8025
            message = EmailMessage()
            message["From"] = "app@example.test"
            message["To"] = mailpit_inbox.address
            message["Subject"] = "From the container"
            message.set_content("Hello")
            with smtplib.SMTP(*mailpit_smtp, timeout=10) as smtp:
                smtp.send_message(message)

            assert mailpit_inbox.wait_for_message().subject == "From the container"
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        ["mailpit: a Docker container of axllent/mailpit, started on first use"]
    )
