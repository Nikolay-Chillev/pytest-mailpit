import os

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def clean_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plugin reads MAILPIT_* and pytest-xdist's variables, in inner sessions too, so
    the machine's must not leak in. The integration tests keep theirs: they say which
    Mailpit to use."""
    if request.node.get_closest_marker("integration"):
        return
    for name in list(os.environ):
        if name.startswith("MAILPIT_") or name.startswith("PYTEST_XDIST_WORKER"):
            monkeypatch.delenv(name)
