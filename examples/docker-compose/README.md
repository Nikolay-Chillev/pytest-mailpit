# pytest-mailpit with docker compose

Mailpit runs next to the application in [`compose.yaml`](compose.yaml). The application sends its email to Mailpit's SMTP port, and the tests read it through Mailpit's API with pytest-mailpit. CI runs this example on every change.

```bash
pip install pytest-mailpit requests
docker compose up -d --build --wait
pytest tests
docker compose down
```

## The two addresses of Mailpit

Inside the compose network, the application reaches Mailpit by its service name, `mailpit`. The tests run on the host, so they reach it through the published port:

| Who | What | Address |
|---|---|---|
| The application (in a container) | SMTP | `mailpit:1025` |
| The tests (on the host) | API and web UI | `http://localhost:8025`, the plugin's default |

To run the tests in a container of the same compose project instead, [`compose.tests.yaml`](compose.tests.yaml) adds a `tests` service. It reaches Mailpit and the application by their service names, and has the application build the links in its email with the address the tests use, `http://app:8000`:

```bash
docker compose -f compose.yaml -f compose.tests.yaml run --rm --build tests
docker compose -f compose.yaml -f compose.tests.yaml down
```

| Who | What | Address |
|---|---|---|
| The tests (in a container) | API and web UI | `http://mailpit:8025/`, from `MAILPIT_URL` |
| The tests (in a container) | The application | `http://app:8000`, from `APP_URL` |

## Waiting for Mailpit

The Mailpit image has a health check, so `depends_on` with `condition: service_healthy` starts the application once Mailpit is ready, and `docker compose up --wait` returns only when every service is healthy.

## Things that save time

- `MP_SMTP_DISABLE_RDNS: "true"`: Mailpit looks up the SMTP client's host name by reverse DNS, which can delay every message by seconds inside containers.
- If Mailpit runs with `MP_ALLOWED_HOSTS` (`--allowed-hosts`, Mailpit 1.31.1 and newer), add the host name the tests use, such as `mailpit`; requests for other host names get 403.
- Mailpit keeps the newest 500 messages by default. A large parallel run can push out messages a slow test still waits for; raise it with `MP_MAX_MESSAGES`.
