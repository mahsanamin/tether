"""M3 acceptance: uploads are stored, served, and reach the routine by path."""

from fastapi.testclient import TestClient

from server.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 24


def test_upload_and_serve():
    with TestClient(app) as client:
        res = client.post(
            "/upload",
            files={"file": ("x.png", PNG, "image/png")},
            data={"kind": "image"},
        )
        assert res.status_code == 200
        aid = res.json()["attachment_id"]
        got = client.get(f"/attachment/{aid}")
        assert got.status_code == 200
        assert got.content == PNG


def test_image_reaches_routine():
    with TestClient(app) as client:
        aid = client.post(
            "/upload",
            files={"file": ("x.png", PNG, "image/png")},
            data={"kind": "image"},
        ).json()["attachment_id"]
        with client.websocket_connect("/ws/ui") as ui:
            ui.receive_json()  # welcome
            with client.websocket_connect("/ws/routine") as rt:
                rt.send_json(
                    {"type": "register", "payload": {"routine_id": "t", "name": "t"}}
                )
                assert rt.receive_json()["type"] == "registered"
                ui.send_json(
                    {
                        "type": "user_message",
                        "payload": {"text": "look", "attachment_ids": [aid]},
                    }
                )
                ui.receive_json()  # user echo
                ta = rt.receive_json()
                assert ta["type"] == "task_available"
                atts = ta["payload"]["attachments"]
                assert len(atts) == 1
                assert atts[0]["kind"] == "image"
                assert atts[0]["url"].endswith(aid)
                assert atts[0]["path"]


def test_safe_image_served_inline():
    with TestClient(app) as client:
        aid = client.post(
            "/upload", files={"file": ("x.png", PNG, "image/png")}
        ).json()["attachment_id"]
        got = client.get(f"/attachment/{aid}")
        assert got.headers["content-type"].startswith("image/png")
        assert "attachment" not in got.headers.get("content-disposition", "")
        assert got.headers.get("x-content-type-options") == "nosniff"


def test_unsafe_upload_served_as_download():
    with TestClient(app) as client:
        aid = client.post(
            "/upload",
            files={"file": ("x.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")},
        ).json()["attachment_id"]
        got = client.get(f"/attachment/{aid}")
        assert got.headers["content-type"].startswith("application/octet-stream")
        assert "attachment" in got.headers.get("content-disposition", "")
        assert got.headers.get("x-content-type-options") == "nosniff"
