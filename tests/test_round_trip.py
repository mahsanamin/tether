"""M1 acceptance: a UI message reaches a routine and its reply comes back live."""

from fastapi.testclient import TestClient

from server.main import app


def test_round_trip():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            welcome = ui.receive_json()
            assert welcome["type"] == "welcome"

            with client.websocket_connect("/ws/routine") as rt:
                rt.send_json(
                    {
                        "type": "register",
                        "payload": {"routine_id": "t", "name": "t", "capabilities": []},
                    }
                )
                assert rt.receive_json()["type"] == "registered"

                ui.send_json({"type": "user_message", "payload": {"text": "hello"}})

                # UI echoes the user's own message first
                echo = ui.receive_json()
                assert echo["type"] == "message_appended"
                assert echo["payload"]["role"] == "user"
                assert echo["payload"]["content"] == "hello"

                # routine receives the raw task
                ta = rt.receive_json()
                assert ta["type"] == "task_available"
                tid = ta["payload"]["task_id"]
                assert ta["payload"]["text"] == "hello"

                rt.send_json({"type": "claim", "payload": {"task_id": tid}})
                cr = rt.receive_json()
                assert cr["type"] == "claim_result" and cr["payload"]["granted"]

                rt.send_json(
                    {"type": "reply", "payload": {"task_id": tid, "content": "hi back"}}
                )

                # the routine reply lands in the UI (after any task_status frames)
                got = False
                for _ in range(6):
                    f = ui.receive_json()
                    if (
                        f["type"] == "message_appended"
                        and f["payload"]["role"] == "routine"
                    ):
                        assert f["payload"]["content"] == "hi back"
                        got = True
                        break
                assert got, "routine reply did not reach the UI"


def test_pending_task_replayed_to_late_routine():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            ui.receive_json()  # welcome
            ui.send_json({"type": "user_message", "payload": {"text": "do it"}})
            ui.receive_json()  # user echo

            # routine connects AFTER the message was sent
            with client.websocket_connect("/ws/routine") as rt:
                rt.send_json(
                    {
                        "type": "register",
                        "payload": {"routine_id": "late", "name": "late"},
                    }
                )
                assert rt.receive_json()["type"] == "registered"
                ta = rt.receive_json()  # replayed task
                assert ta["type"] == "task_available"
                assert ta["payload"]["text"] == "do it"
