"""Point the app at throwaway storage and give each test a fresh database."""

import os
import tempfile
from pathlib import Path

import pytest

_dir = tempfile.mkdtemp(prefix="tether-test-")
os.environ["TETHER_DB"] = os.path.join(_dir, "test.db")
os.environ["TETHER_UPLOAD_DIR"] = os.path.join(_dir, "attachments")
# Tests are hermetic: ignore any machine config.yaml auth token (auth off here;
# test_auth drives the gating explicitly via hub.auth_token).
os.environ["TETHER_AUTH_TOKEN"] = "change-me"


@pytest.fixture(autouse=True)
def _fresh_db():
    """Remove the db before each test so state never leaks between tests."""
    base = os.environ["TETHER_DB"]
    for path in (base, base + "-wal", base + "-shm"):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    yield
