# pytest-mailpit with Testcontainers

[Testcontainers for Python](https://testcontainers-python.readthedocs.io/) can start Mailpit for the test session, so nothing has to run before `pytest`. Its `MailpitContainer` gives the container and its ports; pytest-mailpit adds the inboxes and the waiting. CI runs this example on every change.

```bash
pip install pytest-mailpit "testcontainers[mailpit]"
pytest
```

Docker must be running on the machine.

## How it fits together

[`conftest.py`](conftest.py) has three fixtures:

- `mailpit_container` starts Mailpit once per session and stops it at the end.
- `mailpit_config` overrides the plugin's fixture of the same name: it takes the plugin's settings and replaces the URL with the container's. The `mailpit` client and every `mailpit_inbox` use these settings, so nothing else changes.
- `smtp_server` is the host and port where the application under test sends its email.

[`test_login_code.py`](test_login_code.py) emails a one-time code to the test's inbox and reads it back with `message.code()`, without a fixed `sleep`.

## Notes

- The container uses a random port on the host each time; the fixtures read it from the container, so tests never depend on 8025 being free.
- Configure the application under test with `smtp_server`, for example through its settings or environment, before it sends anything.
- `MailpitContainer` turns on STARTTLS and accepts any SMTP login by default; see its documentation for SMTP users and required TLS.
- The report header of pytest still shows the URL from the settings (`http://localhost:8025/` by default), because the container starts after the header is printed.
