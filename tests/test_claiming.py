"""M5 acceptance: exactly one routine wins a claim; cancel surfaces in chat."""

from fastapi.testclient import TestClient

from server.main import app


def test_two_routines_one_claim():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            ui.receive_json()  # welcome
            with (
                client.websocket_connect("/ws/routine") as r1,
                client.websocket_connect("/ws/routine") as r2,
            ):
                r1.send_json({"type": "register", "payload": {"routine_id": "r1"}})
                r2.send_json({"type": "register", "payload": {"routine_id": "r2"}})
                assert r1.receive_json()["type"] == "registered"
                assert r2.receive_json()["type"] == "registered"

                ui.send_json({"type": "user_message", "payload": {"text": "go"}})
                ui.receive_json()  # user echo

                ta1 = r1.receive_json()
                ta2 = r2.receive_json()
                assert ta1["type"] == "task_available"
                assert ta2["type"] == "task_available"
                tid = ta1["payload"]["task_id"]

                r1.send_json({"type": "claim", "payload": {"task_id": tid}})
                r2.send_json({"type": "claim", "payload": {"task_id": tid}})
                granted = [
                    r1.receive_json()["payload"]["granted"],
                    r2.receive_json()["payload"]["granted"],
                ]
                assert granted.count(True) == 1


def test_cancel_surfaces_in_chat():
    with TestClient(app) as client:
        s = client.post("/api/sessions", json={"title": "c"}).json()
        with client.websocket_connect("/ws/ui") as ui:
            ui.receive_json()  # welcome
            ui.send_json({"type": "subscribe", "payload": {"session_id": s["id"]}})
            ui.send_json({"type": "user_message", "payload": {"text": "slow task"}})

            tid = None
            for _ in range(4):
                f = ui.receive_json()
                if f["type"] == "task_status":
                    tid = f["payload"]["task_id"]
                    break
            assert tid

            ui.send_json({"type": "cancel", "payload": {"task_id": tid}})
            cancelled = False
            for _ in range(5):
                f = ui.receive_json()
                if (
                    f["type"] == "message_appended"
                    and f["payload"]["role"] == "system"
                    and "cancel" in f["payload"]["content"].lower()
                ):
                    cancelled = True
                    break
            assert cancelled
