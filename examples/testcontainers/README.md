# pytest-mailpit with Testcontainers

pytest-mailpit can start Mailpit in a Docker container for the test session, through [Testcontainers for Python](https://testcontainers-python.readthedocs.io/), so nothing has to run before `pytest`. CI runs this example on every change.

```bash
pip install "pytest-mailpit[testcontainers]"
pytest
```

Docker must be running on the machine. The whole setup is one line of [`pytest.ini`](pytest.ini):

```ini
[pytest]
mailpit_container = true
```

or `pytest --mailpit-container` for a single run.

## How it fits together

- The container starts the first time a test needs Mailpit, and stops at the end of the session. Under pytest-xdist every worker gets its own.
- `mailpit_config`, the `mailpit` client and every `mailpit_inbox` use the container's URL, on a random host port, so tests never depend on 8025 being free.
- `mailpit_smtp` is the host and port where the application under test sends its email; [`test_login_code.py`](test_login_code.py) emails a one-time code there and reads it back with `message.code()`.
- The container runs with Chaos enabled, for `mailpit_chaos`, without reverse DNS lookups, which delay messages inside containers, and without asking GitHub for Mailpit's latest release. It is a plain Mailpit, as `docker run axllent/mailpit` gives: no STARTTLS, whose self-signed certificate some SMTP clients would refuse, and an SMTP login that accepts any user.
- `mailpit_container_image` picks the image, for example `axllent/mailpit:v1.31.4` to pin a version.

## Your own container

To configure the container yourself, start it in a session fixture and point the plugin at it by overriding `mailpit_config`; the `mailpit` client, every inbox and `mailpit_smtp` use it. Leave out `mailpit_container = true`, or the plugin starts its own container as well:

```python
import dataclasses

import pytest

from pytest_mailpit import SMTPServer

try:
    from testcontainers.community.mailpit import MailpitContainer
except ImportError:  # Testcontainers before 4.15
    from testcontainers.mailpit import MailpitContainer


@pytest.fixture(scope="session")
def my_mailpit():
    container = (
        MailpitContainer()
        .with_env("MP_MAX_MESSAGES", "5000")
        # As in the plugin's container: no reverse DNS lookups, and Chaos for mailpit_chaos.
        .with_env("MP_SMTP_DISABLE_RDNS", "true")
        .with_env("MP_ENABLE_CHAOS", "true")
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def mailpit_config(mailpit_config, my_mailpit):
    smtp = SMTPServer(my_mailpit.get_container_host_ip(), int(my_mailpit.get_exposed_smtp_port()))
    return dataclasses.replace(mailpit_config, url=my_mailpit.get_base_api_url(), smtp=smtp)
```

Unlike the plugin's, Testcontainers' `MailpitContainer` offers STARTTLS with a self-signed certificate, which SMTP clients that check certificates refuse. Under pytest-xdist every worker starts its own container, but `mailpit_chaos` cannot tell and warns that workers share one Mailpit; silence it with `filterwarnings = ignore:mailpit_chaos makes:pytest_mailpit.MailpitWarning`.
