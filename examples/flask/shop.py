"""A tiny Flask application that emails a password reset link, with Flask-Mail."""

import secrets
from typing import Any

from flask import Flask, request, url_for
from flask_mail import Mail, Message
from markupsafe import escape

mail = Mail()


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        # In development, email goes to Mailpit's SMTP server.
        MAIL_SERVER="localhost",
        MAIL_PORT=1025,
        MAIL_DEFAULT_SENDER="Shop <shop@example.com>",
    )
    app.config.update(config or {})
    mail.init_app(app)
    # Reset tokens and the address each is for; a real application keeps them in its database.
    tokens: dict[str, str] = {}

    @app.post("/forgot-password")
    def forgot_password() -> str:
        email = request.form["email"]
        token = secrets.token_urlsafe(16)
        tokens[token] = email
        link = url_for("reset_password", token=token, _external=True)
        mail.send(
            Message(
                subject="Reset your password",
                recipients=[email],
                body=f"Reset your password: {link}",
                html=f'<p><a href="{escape(link)}">Reset your password</a></p>',
            )
        )
        return "Check your inbox."

    @app.get("/reset-password/<token>")
    def reset_password(token: str) -> tuple[str, int]:
        email = tokens.pop(token, None)
        if email is None:
            return "This link is invalid or was already used.", 400
        return f"Choose a new password for {escape(email)}.", 200

    return app
