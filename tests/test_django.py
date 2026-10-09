"""mailpit_django and the hint about Django's outbox, with Django set up in this process."""

import sys
import warnings
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
    MAILPIT_BACKEND,
    OUTBOX_HINT,
    SMTP_BACKEND,
    email_settings,
    keeps_email_in_memory,
    outbox_hint,
)
from tests.test_waiting import page

URL = "http://localhost:8025/"
# The inner sessions set Django up themselves, whether pytest-django is installed or not.
NO_PYTEST_DJANGO = ("-p", "no:django")
# Django 6.1 configures email with MAILERS, older versions with EMAIL_BACKEND.
HAS_MAILERS = django.VERSION >= (6, 1)
# A project that logs in to its real SMTP server with TLS, and sends from that login.
SENDER = "no-reply@shop.example.com"
EMAIL_SETTINGS = {
    "EMAIL_HOST": "smtp.example.net",
    "EMAIL_HOST_USER": SENDER,
    "EMAIL_HOST_PASSWORD": "secret",
    "EMAIL_USE_TLS": True,
}


@pytest.fixture
def server() -> Iterator[responses.RequestsMock]:
    """A mocked Mailpit without messages."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{URL}api/v1/search", json=page())
        mock.get(f"{URL}api/v1/messages", json=page())
        mock.delete(f"{URL}api/v1/messages", body="ok")
        yield mock


def django_test_environment(**project_settings: Any) -> Iterator[None]:
    """Django set up as its test runner and pytest-django do: email stays in memory."""
    with warnings.catch_warnings():  # Django 6.1 warns about the EMAIL_* settings
        warnings.simplefilter("ignore")
        settings.configure(**project_settings)
        setup_test_environment()
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        teardown_test_environment()
    settings._wrapped = empty  # unconfigured again, for the other tests


@pytest.fixture
def email_settings_project() -> Iterator[None]:
    """A project on the EMAIL_* settings: every Django, and 6.1 projects not migrated yet."""
    yield from django_test_environment(**EMAIL_SETTINGS)


@pytest.fixture
def mailers_project() -> Iterator[None]:
    """A Django 6.1 project on MAILERS."""
    if not HAS_MAILERS:
        pytest.skip("MAILERS needs Django 6.1")
    mailers = {"default": {"OPTIONS": {"host": "smtp.example.net"}}, "alerts": {}}
    yield from django_test_environment(MAILERS=mailers)


# The settings


@pytest.mark.parametrize("version", [(5, 2, 18, "final", 0), (6, 0, 9), (6, 1, 2, "final", 0)])
def test_without_mailers_the_email_backend_points_at_mailpit(version: tuple[Any, ...]) -> None:
    assert email_settings(version, None, SMTPServer("mail.test", 2525)) == {
        "EMAIL_BACKEND": MAILPIT_BACKEND,
        "EMAIL_HOST": "mail.test",
        "EMAIL_PORT": 2525,
    }


def test_django_before_6_1_ignores_mailers() -> None:
    assert "MAILERS" not in email_settings((6, 0, 9), {"default": {}}, SMTPServer("mail.test", 25))


def test_django_6_1_with_mailers_sends_every_mailer_to_mailpit() -> None:
    mailers = {"default": {"OPTIONS": {"host": "smtp.example.net"}}, "alerts": {}}

    configured = email_settings((6, 1, 2, "final", 0), mailers, SMTPServer("mail.test", 2525))

    mailpit = {"BACKEND": SMTP_BACKEND, "OPTIONS": {"host": "mail.test", "port": 2525}}
    assert configured == {"MAILERS": {"default": mailpit, "alerts": mailpit}}


def test_django_6_1_with_empty_mailers_gets_a_default_one() -> None:
    configured = email_settings((6, 1), {}, SMTPServer("mail.test", 2525))

    assert list(configured["MAILERS"]) == ["default"]


# The fixture, in inner sessions

SENDS_TO_MAILPIT = """
import warnings

from django.conf import settings
from django.core import mail


def backends():
    with warnings.catch_warnings():  # Django 6.1 deprecates get_connection(), here only
        warnings.simplefilter("ignore")
        if hasattr(settings, "MAILERS"):  # a Django 6.1 project on MAILERS
            return [mail.mailers[alias] for alias in mail.mailers]
        return [mail.get_connection()]


def test_with_mailpit(mailpit_django):
    for backend in backends():
        assert backend.__module__.startswith(("django.core.mail.backends.smtp", "pytest_mailpit"))
        assert (backend.host, backend.port) == ("mail.test", 2525)
        assert not backend.username and not backend.password
        assert not backend.use_tls and not backend.use_ssl


def test_without_mailpit_again():
    for backend in backends():
        assert type(backend).__module__ == "django.core.mail.backends.locmem"
"""


@pytest.mark.parametrize("project", ["email_settings_project", "mailers_project"])
def test_the_fixture_sends_djangos_email_to_mailpit_for_one_test(
    pytester: pytest.Pytester,
    server: responses.RequestsMock,
    request: pytest.FixtureRequest,
    project: str,
) -> None:
    request.getfixturevalue(project)
    pytester.makeini("[pytest]\nmailpit_smtp = mail.test:2525\n")
    pytester.makepyfile(SENDS_TO_MAILPIT)

    # -W error: Django 6.1's deprecation warnings about EMAIL_* must not reach the tests.
    pytester.runpytest("-W", "error", *NO_PYTEST_DJANGO).assert_outcomes(passed=2)


def test_the_project_keeps_its_email_settings(
    pytester: pytest.Pytester, server: responses.RequestsMock, email_settings_project: None
) -> None:
    # Code that sends from EMAIL_HOST_USER must send from it in Mailpit too.
    pytester.makepyfile(
        f"""
        import warnings

        from django.conf import settings
        from django.core.mail import EmailMessage


        def test_sender(mailpit_django):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                assert settings.EMAIL_HOST_USER == {SENDER!r}
                assert settings.EMAIL_USE_TLS
                message = EmailMessage("Hi", "Body", settings.EMAIL_HOST_USER, ["a@example.com"])
            assert message.from_email == {SENDER!r}
        """
    )

    pytester.runpytest(*NO_PYTEST_DJANGO).assert_outcomes(passed=1)


def test_the_fixture_needs_django(
    pytester: pytest.Pytester, server: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "django", None)
    pytester.makepyfile("def test_django(mailpit_django): pass")

    result = pytester.runpytest(*NO_PYTEST_DJANGO)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["mailpit_django needs Django: pip install django"])
    assert "During handling of the above exception" not in result.stdout.str()


def test_the_fixture_needs_djangos_settings(
    pytester: pytest.Pytester, server: responses.RequestsMock
) -> None:
    pytester.makepyfile("def test_django(mailpit_django): pass")

    result = pytester.runpytest(*NO_PYTEST_DJANGO)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "mailpit_django needs Django's settings: use pytest-django with "
            "DJANGO_SETTINGS_MODULE, or call django.conf.settings.configure()."
        ]
    )
    assert "During handling of the above exception" not in result.stdout.str()


# The hint


@pytest.mark.parametrize("project", ["email_settings_project", "mailers_project"])
def test_a_message_kept_in_djangos_outbox_gets_a_hint(
    server: responses.RequestsMock, request: pytest.FixtureRequest, project: str
) -> None:
    request.getfixturevalue(project)

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no deprecation warning instead of the failure
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


DJANGO_6_1 = (6, 1, 2, "final", 0)
DJANGO_5_2 = (5, 2, 18, "final", 0)


@pytest.mark.parametrize(
    ("version", "django_settings", "in_memory"),
    [
        (DJANGO_5_2, {"EMAIL_BACKEND": LOCMEM_BACKEND}, True),
        (DJANGO_5_2, {"EMAIL_BACKEND": SMTP_BACKEND}, False),
        # Django 5.2 ignores MAILERS: what counts is EMAIL_BACKEND.
        (
            DJANGO_5_2,
            {"MAILERS": {"default": {"BACKEND": SMTP_BACKEND}}, "EMAIL_BACKEND": LOCMEM_BACKEND},
            True,
        ),
        (DJANGO_6_1, {"MAILERS": {"default": {"BACKEND": SMTP_BACKEND}, "tests": {}}}, False),
        (DJANGO_6_1, {"MAILERS": {"default": {"BACKEND": LOCMEM_BACKEND}}}, True),
        # With MAILERS, Django 6.1 refuses to read EMAIL_BACKEND.
        (DJANGO_6_1, {"MAILERS": {}, "EMAIL_BACKEND": LOCMEM_BACKEND}, False),
        (DJANGO_6_1, {"EMAIL_BACKEND": LOCMEM_BACKEND}, True),
        (DJANGO_6_1, {}, False),
    ],
)
def test_keeps_email_in_memory(
    version: tuple[Any, ...], django_settings: dict[str, Any], in_memory: bool
) -> None:
    keeps = keeps_email_in_memory(SimpleNamespace(**django_settings), version=version)

    assert keeps is in_memory
