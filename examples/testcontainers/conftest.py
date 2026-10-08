"""Start Mailpit with Testcontainers and point pytest-mailpit at it."""

import dataclasses

import pytest
from testcontainers.community.mailpit import MailpitContainer

from pytest_mailpit import MailpitConfig


@pytest.fixture(scope="session")
def mailpit_container():
    # Reverse DNS lookups of SMTP clients can delay every message by seconds in containers.
    container = MailpitContainer().with_env("MP_SMTP_DISABLE_RDNS", "true")
    with container:
        yield container


@pytest.fixture(scope="session")
def mailpit_config(mailpit_config: MailpitConfig, mailpit_container) -> MailpitConfig:
    """The plugin's settings, with the URL of the container.

    Overriding mailpit_config is enough: the mailpit client and every inbox use it.
    """
    return dataclasses.replace(mailpit_config, url=mailpit_container.get_base_api_url())


@pytest.fixture(scope="session")
def smtp_server(mailpit_container) -> tuple[str, int]:
    """Where the application under test sends its email."""
    return mailpit_container.get_container_host_ip(), mailpit_container.get_exposed_smtp_port()
