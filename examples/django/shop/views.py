"""Sign up with an email address, and confirm it with the link in the email."""

from django.core import signing
from django.core.mail import send_mail
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.urls import reverse
from django.utils.html import escape

SALT = "shop.confirm"


def sign_up(request: HttpRequest) -> HttpResponse:
    email = request.POST.get("email", "")
    if "@" not in email:
        return HttpResponseBadRequest("An email address is required.")
    token = signing.dumps(email, salt=SALT)
    link = request.build_absolute_uri(reverse("confirm", args=[token]))
    send_mail(
        subject="Confirm your email",
        message=f"Welcome to the shop! Confirm your email: {link}",
        from_email=None,
        recipient_list=[email],
        html_message=(
            f'<p>Welcome to the shop!</p><p><a href="{escape(link)}">Confirm your email</a></p>'
        ),
    )
    return HttpResponse("Check your inbox for the confirmation link.")


def confirm(request: HttpRequest, token: str) -> HttpResponse:
    try:
        email = signing.loads(token, salt=SALT, max_age=3600)
    except signing.BadSignature:
        return HttpResponseBadRequest("This link is invalid or has expired.")
    return HttpResponse(f"{escape(email)} is confirmed.")
