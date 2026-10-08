import secrets
import smtplib
from email.message import EmailMessage


def send_login_code(smtp_server: tuple[str, int], address: str) -> str:
    """Stands in for the application under test: emails a one-time login code."""
    code = f"{secrets.randbelow(1_000_000):06}"
    message = EmailMessage()
    message["From"] = "Shop <no-reply@shop.example.com>"
    message["To"] = address
    message["Subject"] = "Your login code"
    message.set_content(f"Your login code is {code}. It expires in 10 minutes.")
    with smtplib.SMTP(*smtp_server, timeout=10) as smtp:
        smtp.send_message(message)
    return code


def test_login_code_arrives(mailpit_inbox, mailpit_smtp):
    sent = send_login_code(mailpit_smtp, mailpit_inbox.address)

    message = mailpit_inbox.wait_for_message(subject="Your login code")

    assert message.code() == sent
