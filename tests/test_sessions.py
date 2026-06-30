"""M2 acceptance: sessions are isolated, persistent, and CRUD works."""

from fastapi.testclient import TestClient

from server.main import app


def test_session_crud_and_isolation():
    with TestClient(app) as client:
        a = client.post("/api/sessions", json={"title": "A"}).json()
        b = client.post("/api/sessions", json={"title": "B"}).json()

        client.post(f"/api/sessions/{a['id']}/reply", json={"content": "alpha"})
        client.post(f"/api/sessions/{b['id']}/reply", json={"content": "beta"})

        ma = client.get(f"/api/sessions/{a['id']}/messages").json()
        mb = client.get(f"/api/sessions/{b['id']}/messages").json()
        assert any(m["content"] == "alpha" for m in ma)
        assert all(m["content"] != "beta" for m in ma)
        assert any(m["content"] == "beta" for m in mb)

        client.patch(f"/api/sessions/{a['id']}", json={"title": "A2"})
        sessions = client.get("/api/sessions").json()
        assert any(s["id"] == a["id"] and s["title"] == "A2" for s in sessions)

        client.delete(f"/api/sessions/{b['id']}")
        sessions = client.get("/api/sessions").json()
        assert all(s["id"] != b["id"] for s in sessions)


def test_incremental_read():
    with TestClient(app) as client:
        s = client.post("/api/sessions", json={"title": "inc"}).json()
        client.post(f"/api/sessions/{s['id']}/reply", json={"content": "first"})
        msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
        cursor = msgs[-1]["created_at"]
        client.post(f"/api/sessions/{s['id']}/reply", json={"content": "second"})
        after = client.get(
            f"/api/sessions/{s['id']}/messages", params={"after": cursor}
        ).json()
        assert [m["content"] for m in after] == ["second"]
