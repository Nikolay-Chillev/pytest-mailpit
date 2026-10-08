"""A tiny Django project that emails a confirmation link at sign-up."""

SECRET_KEY = "only-for-this-example"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
ROOT_URLCONF = "shop.urls"
INSTALLED_APPS: list[str] = []
DATABASES: dict[str, dict[str, str]] = {}
DEFAULT_FROM_EMAIL = "Shop <shop@example.com>"

# In development, email goes to Mailpit's SMTP server (before Django 6.1:
# EMAIL_HOST and EMAIL_PORT). During tests Django keeps it in memory, unless
# the test uses mailpit_django.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {"host": "localhost", "port": 1025},
    },
}
