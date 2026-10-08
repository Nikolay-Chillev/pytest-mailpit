"""mailpit_django and the hint about Django's outbox, with Django set up in this process."""

import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import django
import pytest
import responses
from django.conf import settings
from django.test.utils import setup_test_environment, teardown_test_environment
from django.utils.functional import empty

from pytest_mailpit import MailpitAssertionError, MailpitClient, SMTPServer
from pytest_mailpit._django import (
    LOCMEM_BACKEND,
    OUTBOX_HINT,
    SMTP_BACKEND,
    email_settings,
    keeps_email_in_memory,
    outbox_hint,
)
from tests import samples
from tests.test_waiting import page

URL = "http://localhost:8025/"
# Django 6.1 configures email with MAILERS, older versions with EMAIL_BACKEND.
HAS_MAILERS = django.VERSION >= (6, 1)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MAILPIT_URL", "MAILPIT_SMTP", "PYTEST_XDIST_WORKER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server() -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit without messages."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/info", json=samples.INFO)
        mock.get(f"{URL}api/v1/search", json=page())
        mock.get(f"{URL}api/v1/messages", json=page())
        mock.delete(f"{URL}api/v1/messages", body="ok")
        yield mock


@pytest.fixture
def django_test_environment() -> Iterator[None]:
    """Django set up as its test runner and pytest-django do: email stays in memory."""
    mailers = {"default": {"OPTIONS": {"host": "smtp.example.net"}}, "alerts": {}}
    settings.configure(**({"MAILERS": mailers} if HAS_MAILERS else {}))
    setup_test_environment()
    yield
    teardown_test_environment()
    settings._wrapped = empty  # unconfigured again, for the other tests


# The settings


def test_older_django_gets_the_email_settings() -> None:
    assert email_settings((5, 2, 18, "final", 0), None, SMTPServer("mail.test", 2525)) == {
        "EMAIL_BACKEND": SMTP_BACKEND,
        "EMAIL_HOST": "mail.test",
        "EMAIL_PORT": 2525,
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": False,
        "EMAIL_USE_SSL": False,
    }


def test_django_6_0_has_no_mailers_yet() -> None:
    assert "MAILERS" not in email_settings((6, 0, 9), {"default": {}}, SMTPServer("mail.test", 25))


def test_django_6_1_sends_every_mailer_to_mailpit() -> None:
    mailers = {"default": {"OPTIONS": {"host": "smtp.example.net"}}, "alerts": {}}

    configured = email_settings((6, 1, 2, "final", 0), mailers, SMTPServer("mail.test", 2525))

    mailpit = {"BACKEND": SMTP_BACKEND, "OPTIONS": {"host": "mail.test", "port": 2525}}
    assert configured == {"MAILERS": {"default": mailpit, "alerts": mailpit}}


def test_django_6_1_without_mailers_gets_a_default_one() -> None:
    configured = email_settings((6, 1), None, SMTPServer("mail.test", 2525))

    assert list(configured["MAILERS"]) == ["default"]


# The fixture, in inner sessions

USES_MAILPIT_DJANGO = """
from django.core import mail


def backends():
    if hasattr(mail, "mailers"):  # Django 6.1+
        return [mail.mailers[alias] for alias in mail.mailers]
    return [mail.get_connection()]


def test_with_mailpit(mailpit_django):
    for backend in backends():
        assert type(backend).__module__ == "django.core.mail.backends.smtp"
        assert (backend.host, backend.port) == ("mail.test", 2525)
        assert not backend.username and not backend.use_tls and not backend.use_ssl


def test_without_mailpit_again():
    for backend in backends():
        assert type(backend).__module__ == "django.core.mail.backends.locmem"
"""


def test_the_fixture_sends_djangos_email_to_mailpit_for_one_test(
    pytester: pytest.Pytester, server: responses.RequestsMock, django_test_environment: None
) -> None:
    pytester.makeini("[pytest]\nmailpit_smtp = mail.test:2525\n")
    pytester.makepyfile(USES_MAILPIT_DJANGO)

    pytester.runpytest().assert_outcomes(passed=2)


def test_the_fixture_needs_django(
    pytester: pytest.Pytester, server: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "django", None)
    pytester.makepyfile("def test_django(mailpit_django): pass")

    result = pytester.runpytest()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["mailpit_django needs Django: pip install django"])
    assert "During handling of the above exception" not in result.stdout.str()


# The hint


def test_a_message_kept_in_djangos_outbox_gets_a_hint(
    server: responses.RequestsMock, django_test_environment: None
) -> None:
    with pytest.raises(MailpitAssertionError) as failure:
        MailpitClient(URL).wait_for_message(recipient="new@example.com", timeout=0)

    assert str(failure.value).endswith(f"Mailpit has no messages.\n{OUTBOX_HINT}")


def test_no_hint_without_django_set_up(
    server: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(MailpitAssertionError) as failure:
        MailpitClient(URL).wait_for_message(recipient="new@example.com", timeout=0)

    assert str(failure.value).endswith("Mailpit has no messages.")
    monkeypatch.delitem(sys.modules, "django.conf")
    assert outbox_hint() == ""


@pytest.mark.parametrize(
    ("django_settings", "in_memory"),
    [
        ({"EMAIL_BACKEND": LOCMEM_BACKEND}, True),
        ({"EMAIL_BACKEND": SMTP_BACKEND}, False),
        ({"MAILERS": {"default": {"BACKEND": SMTP_BACKEND}, "tests": {}}}, False),
        ({"MAILERS": {"default": {"BACKEND": LOCMEM_BACKEND}}}, True),
        # With MAILERS, Django 6.1 refuses to read EMAIL_BACKEND.
        ({"MAILERS": {}, "EMAIL_BACKEND": LOCMEM_BACKEND}, False),
        ({}, False),
    ],
)
def test_keeps_email_in_memory(django_settings: dict[str, Any], in_memory: bool) -> None:
    assert keeps_email_in_memory(SimpleNamespace(**django_settings)) is in_memory
