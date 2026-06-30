"""Widgets: clickable predefined-command buttons, stored server-side."""

from fastapi.testclient import TestClient

from server.main import app


def test_widget_crud():
    with TestClient(app) as client:
        w = client.post(
            "/api/widgets",
            json={"name": "Deploy staging", "command": "./deploy.sh . 'go'"},
        ).json()
        assert w["name"] == "Deploy staging"
        assert w["params"] == []  # no ask-on-click params by default
        assert any(x["id"] == w["id"] for x in client.get("/api/widgets").json())
        client.delete(f"/api/widgets/{w['id']}")
        assert all(x["id"] != w["id"] for x in client.get("/api/widgets").json())


def test_widget_ask_on_click_params_round_trip():
    """A widget can carry {{key}} placeholders + a params spec; the server stores
    and returns it verbatim (the client fills and substitutes at click time)."""
    with TestClient(app) as client:
        params = [
            {"key": "ticket", "label": "--ticket TICKET", "default": ""},
            {"key": "base", "label": "--base", "default": "main"},
        ]
        w = client.post(
            "/api/widgets",
            json={
                "name": "Start Task",
                "command": (
                    "./start-task.sh --repo /r --ticket {{ticket}} --base {{base}}"
                ),
                "params": params,
            },
        ).json()
        assert [p["key"] for p in w["params"]] == ["ticket", "base"]
        assert w["params"][1]["default"] == "main"

        # garbage param entries are sanitized away; label defaults to the key
        u = client.put(
            f"/api/widgets/{w['id']}",
            json={
                "name": "Start Task",
                "command": "echo {{x}}",
                "params": [{"key": "x"}, {"nope": 1}, {"key": "bad key!"}],
            },
        ).json()
        assert [p["key"] for p in u["params"]] == ["x"]
        assert u["params"][0]["label"] == "x"

        with client.websocket_connect("/ws/ui") as ui:
            welcome = ui.receive_json()
            got = next(x for x in welcome["payload"]["widgets"] if x["id"] == w["id"])
            assert got["params"][0]["key"] == "x"


def test_widgets_in_welcome():
    with TestClient(app) as client:
        client.post("/api/widgets", json={"name": "W1", "command": "echo hi"})
        with client.websocket_connect("/ws/ui") as ui:
            welcome = ui.receive_json()
            assert welcome["type"] == "welcome"
            assert any(x["name"] == "W1" for x in welcome["payload"]["widgets"])


def test_update_widget():
    with TestClient(app) as client:
        w = client.post("/api/widgets", json={"name": "A", "command": "echo a"}).json()
        u = client.put(
            f"/api/widgets/{w['id']}", json={"name": "B", "command": "echo b"}
        ).json()
        assert u["name"] == "B" and u["command"] == "echo b"
        lst = client.get("/api/widgets").json()
        assert any(x["id"] == w["id"] and x["name"] == "B" for x in lst)
        assert (
            client.put(
                "/api/widgets/nope", json={"name": "x", "command": "y"}
            ).status_code
            == 404
        )


def test_help_probe_routes_to_builder_not_chat():
    """The widget builder's --help probe rides the task queue, the routine runs
    `<command> --help`, and the result returns as help_result, never as chat."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            welcome = ui.receive_json()
            assert welcome["type"] == "welcome"
            sid = welcome["payload"]["session_id"]
            with client.websocket_connect("/ws/routine") as rt:
                rt.send_json(
                    {
                        "type": "register",
                        "payload": {"routine_id": "shell", "name": "s"},
                    }
                )
                assert rt.receive_json()["type"] == "registered"

                ui.send_json({"type": "help_request", "payload": {"command": "mytool"}})

                ta = rt.receive_json()
                assert ta["type"] == "task_available"
                assert ta["payload"]["text"] == "mytool --help"
                tid = ta["payload"]["task_id"]

                rt.send_json({"type": "claim", "payload": {"task_id": tid}})
                assert rt.receive_json()["type"] == "claim_result"

                help_text = "usage: mytool [-h] dir\n\noptions:\n  -n NAME  the name\n"
                rt.send_json(
                    {"type": "reply", "payload": {"task_id": tid, "content": help_text}}
                )

                hr = ui.receive_json()
                assert hr["type"] == "help_result"
                assert hr["payload"]["ok"] is True
                assert hr["payload"]["command"] == "mytool"
                assert "options:" in hr["payload"]["text"]

        # the probe must leave no trace in the chat thread
        assert client.get(f"/api/sessions/{sid}/messages").json() == []


def test_help_probe_rejects_shell_syntax():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            assert ui.receive_json()["type"] == "welcome"
            ui.send_json({"type": "help_request", "payload": {"command": "rm -rf /"}})
            hr = ui.receive_json()
            assert hr["type"] == "help_result"
            assert hr["payload"]["ok"] is False
