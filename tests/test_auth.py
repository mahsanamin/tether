"""M7 acceptance: when a real token is set, WS connects require it."""

from fastapi.testclient import TestClient

from server.main import app, hub


def test_auth_rejects_wrong_token():
    hub.auth_token = "secret"
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/ui") as ui:
                ui.send_json({"type": "hello", "payload": {"token": "wrong"}})
                f = ui.receive_json()
                assert f["type"] == "error"
                assert f["payload"]["code"] == "unauthorized"
    finally:
        hub.auth_token = ""


def test_auth_allows_correct_token():
    hub.auth_token = "secret"
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/ui") as ui:
                ui.send_json({"type": "hello", "payload": {"token": "secret"}})
                assert ui.receive_json()["type"] == "welcome"
    finally:
        hub.auth_token = ""
