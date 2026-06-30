"""M0 acceptance: the app boots and /health responds."""

from fastapi.testclient import TestClient

from server.main import app


def test_health_returns_ok():
    # The context manager runs the lifespan, which creates the database file.
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_ui_shell_served():
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "tether" in resp.text
