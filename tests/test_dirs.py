"""Directory picker endpoint: lists subdirectory names of a host path."""

import os

from fastapi.testclient import TestClient

from server.main import app

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_list_dirs_returns_subdirs():
    with TestClient(app) as client:
        d = client.get("/api/dirs", params={"path": REPO_ROOT}).json()
        assert "server" in d["dirs"]
        assert "web" in d["dirs"]
        assert d["parent"]


def test_list_dirs_bad_path():
    with TestClient(app) as client:
        r = client.get("/api/dirs", params={"path": "/no/such/dir/xyz123"})
        assert r.status_code == 400
