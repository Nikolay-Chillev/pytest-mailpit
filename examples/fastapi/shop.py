"""A tiny FastAPI application that emails a login code in a background task."""

import secrets
import smtplib
from email.message import EmailMessage
from typing import Annotated, NamedTuple

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel


class SMTPSettings(NamedTuple):
    # In development, email goes to Mailpit's SMTP server.
    host: str = "localhost"
    port: int = 1025


def smtp_settings() -> SMTPSettings:
    return SMTPSettings()


class CodeRequest(BaseModel):
    email: str


class Login(BaseModel):
    email: str
    code: str


app = FastAPI()
# The code sent to each address; a real application keeps them in its database.
codes: dict[str, str] = {}


def send_code(smtp: SMTPSettings, email: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = "Shop <shop@example.com>"
    message["To"] = email
    message["Subject"] = "Your login code"
    message.set_content(f"Your login code is {code}. It expires in 10 minutes.")
    with smtplib.SMTP(smtp.host, smtp.port, timeout=10) as server:
        server.send_message(message)


@app.post("/login/code")
def request_code(
    body: CodeRequest,
    background: BackgroundTasks,
    smtp: Annotated[SMTPSettings, Depends(smtp_settings)],
) -> dict[str, str]:
    code = f"{secrets.randbelow(1_000_000):06}"
    codes[body.email] = code
    background.add_task(send_code, smtp, body.email, code)
    return {"detail": "Check your inbox."}


@app.post("/login")
def login(body: Login) -> dict[str, str]:
    if codes.get(body.email) != body.code:
        raise HTTPException(status_code=401, detail="Wrong or expired code.")
    del codes[body.email]
    return {"detail": f"Logged in as {body.email}"}
