# Migrating from MailHog to Mailpit and pytest-mailpit

[MailHog](https://github.com/mailhog/MailHog) has had no release since v1.0.1 in August 2020, and its author no longer maintains it. [Mailpit](https://mailpit.axllent.org) took its place: it is actively maintained, and DDEV, Laravel Sail and cookiecutter-django all switched to it. It listens on the same ports, so the application under test does not change. The tests do, and that is where pytest-mailpit helps.

## 1. Swap the container

```yaml
services:
  mailpit:
    image: axllent/mailpit    # was: mailhog/mailhog
    ports:
      - "8025:8025"           # web UI and API, as MailHog
      - "1025:1025"           # SMTP, as MailHog
```

The application keeps sending to port 1025. If it used a different host name, such as `mailhog`, rename the service or point the application at `mailpit`.

| MailHog | Mailpit |
|---|---|
| `MH_SMTP_BIND_ADDR`, `-smtp-bind-addr` | `MP_SMTP_BIND_ADDR`, `--smtp` |
| `MH_UI_BIND_ADDR` and `MH_API_BIND_ADDR` | `MP_UI_BIND_ADDR`, `--listen` (one address for both) |
| `MH_UI_WEB_PATH` (without slashes, e.g. `mailhog`) | `MP_WEBROOT`, `--webroot` |
| `MH_AUTH_FILE`, `-auth-file` | `MP_UI_AUTH_FILE`, `--ui-auth-file`, or `MP_UI_AUTH` |
| `MH_STORAGE` (memory, maildir, mongodb) | `MP_DATABASE`: a SQLite file; by default a temporary one, removed when Mailpit stops |
| `-invite-jim` (Jim, the chaos monkey) | `MP_ENABLE_CHAOS`, `--enable-chaos` (Chaos) |

## 2. Replace the conftest glue

A typical MailHog setup reads the API by hand, clears the whole mailbox before each test, polls in a loop, and decodes the body itself:

```python
MAILHOG = os.environ.get("MAILHOG_URL", "http://localhost:8025")


@pytest.fixture(autouse=True)
def clear_mailhog():
    requests.delete(f"{MAILHOG}/api/v1/messages")


def wait_for_email(to):
    for _ in range(50):
        found = requests.get(f"{MAILHOG}/api/v2/search", params={"kind": "to", "query": to})
        if found.json()["items"]:
            return found.json()["items"][0]
        time.sleep(0.2)
    raise AssertionError(f"No email to {to}")


def test_password_reset(app_client):
    app_client.post("/forgot-password", data={"email": "user@example.com"})
    email = wait_for_email("user@example.com")
    assert email["Content"]["Headers"]["Subject"][0] == "Reset your password"
    body = quopri.decodestring(email["Content"]["Body"]).decode()
    link = re.search(r"https://\S+/reset/\S+", body).group()
```

With pytest-mailpit, all of that goes:

```python
def test_password_reset(app_client, mailpit_inbox):
    app_client.post("/forgot-password", data={"email": mailpit_inbox.address})
    message = mailpit_inbox.wait_for_message(subject="Reset your password")
    link = message.link("/reset/")
```

The old version also breaks under pytest-xdist: every worker deletes the mailbox of the others, and every test waits on the same address. `mailpit_inbox` gives each test its own address and deletes only that test's messages.

## 3. The API, call by call

| MailHog | Mailpit API | pytest-mailpit |
|---|---|---|
| `GET /api/v2/messages` | `GET /api/v1/messages` | `mailpit.messages()` |
| `GET /api/v2/search?kind=to&query=a@x.com` | `GET /api/v1/search?query=to:"a@x.com"` | `mailpit_inbox.wait_for_message()`, or `mailpit.search(build_query(to="a@x.com"))` |
| `kind=from` | `from:"..."` | `build_query(sender="...")` |
| `kind=containing` | text without a prefix | `build_query("...")` |
| `GET /api/v1/messages/{id}` | `GET /api/v1/message/{ID}` | `mailpit.get_message(id)` |
| `GET /api/v1/messages/{id}/download` | `GET /api/v1/message/{ID}/raw` | `mailpit.get_raw(id)` |
| `GET /api/v1/messages/{id}/mime/part/{index}/download` | `GET /api/v1/message/{ID}/part/{PartID}` | `mailpit.get_attachment(message.attachment(...))` |
| `DELETE /api/v1/messages` | `DELETE /api/v1/messages` | `mailpit.delete_all()`, though the inbox cleans up after itself |
| `DELETE /api/v1/messages/{id}` | `DELETE /api/v1/messages` with `{"IDs": [...]}` | `mailpit.delete_messages([id])` |

## 4. The message, field by field

| MailHog JSON | pytest-mailpit |
|---|---|
| `Content.Headers.Subject[0]` | `message.subject` |
| `From.Mailbox` + `@` + `From.Domain` | `message.sender.address` |
| `To[]` (the envelope recipients) | `message.to`, `message.cc`, `message.bcc` |
| `Content.Body`, still quoted-printable or base64 encoded | `message.text` and `message.html`, decoded |
| A regular expression over the body for a link or a code | `message.link(...)`, `message.code()` |
| `MIME.Parts` | `message.attachments`, `message.inline` |
| `Created` | `summary.created` of a search result |
| `Raw.Data` | `mailpit.get_raw(message.id)` |

## 5. What behaves differently

- **Search matches substrings.** `to:"a@x.com"` also finds `ba@x.com`. pytest-mailpit's waiting methods check the whole address after searching.
- **Mailpit keeps the newest 500 messages** by default and deletes older ones; MailHog kept everything in memory. Raise the limit with `MP_MAX_MESSAGES` for large parallel runs.
- **Reading a whole message marks it as read**, which matters if a search uses `is:unread`.
- **Plus addresses become tags**: mail to `user+orders@x.com` is tagged `orders` automatically.
- **Reverse DNS lookups** of SMTP clients can delay messages inside containers; set `MP_SMTP_DISABLE_RDNS=true`.
