"""A tiny application that sends a confirmation email when someone signs up.

It stands in for your application: what matters is that it sends email over
SMTP to the host and port in SMTP_HOST and SMTP_PORT.
"""

import os
import secrets
import smtplib
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000")


def send_confirmation(address: str) -> None:
    link = f"{PUBLIC_URL}/confirm?token={secrets.token_urlsafe(16)}"
    message = EmailMessage()
    message["From"] = "Shop <no-reply@shop.example.com>"
    message["To"] = address
    message["Subject"] = "Confirm your email"
    message.set_content(f"Welcome! Confirm your email: {link}")
    message.add_alternative(
        f'<p>Welcome!</p><p><a href="{link}">Confirm your email</a></p>', subtype="html"
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._reply(200 if self.path == "/health" else 404)

    def do_POST(self) -> None:
        if self.path != "/sign-up":
            self._reply(404)
            return
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        send_confirmation(form["email"][0])
        self._reply(201)

    def _reply(self, status: int) -> None:
        self.send_response(status)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
