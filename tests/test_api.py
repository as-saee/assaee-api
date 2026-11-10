from datetime import timedelta

import pytest

from app import config, ntfy
from app.main import app
from app.routes import get_publisher


def make(client, name="Book", **kw):
    r = client.post("/threads", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_needs_only_a_name_and_gets_a_default_rhythm(client):
    t = make(client, "Reading", kind="book")
    assert t["interval_hours"] == 24 and not t["quiet"] and t["last_touched"] is None
    assert t["active_days"] == [0, 1, 2, 3, 4, 5, 6]
    assert make(client)["kind"] == "other"


def test_validation(client):
    assert client.post("/threads", json={"name": ""}).status_code == 422
    assert client.post("/threads", json={"name": "x", "kind": "nope"}).status_code == 422
    assert client.post("/threads", json={"name": "x", "interval_hours": 0}).status_code == 422
    assert client.post("/threads", json={"name": "x", "active_days": [7]}).status_code == 422
    assert client.post("/threads", json={"name": "x", "active_days": []}).status_code == 422


def test_touch_records_and_resets(client, clock):
    t = make(client, kind="book")
    clock.advance(days=4)
    assert client.get("/threads").json()[0]["quiet"]
    touched = client.post(f"/threads/{t['id']}/touch").json()
    assert not touched["quiet"] and touched["elapsed_hours"] == 0
    assert touched["last_touched"].startswith("2026-10-16")


def test_snooze_hides_nudge_and_backs_off(client, clock):
    t = make(client, kind="book")
    clock.advance(days=4)
    assert len(client.get("/nudges").json()["nudges"]) == 1
    client.post(f"/threads/{t['id']}/snooze", json={"hours": 5})
    assert client.get("/nudges").json()["nudges"] == []
    clock.advance(hours=6)
    assert len(client.get("/nudges").json()["nudges"]) == 1  # snooze over
    client.post(f"/threads/{t['id']}/snooze", json={"hours": 1})
    client.post(f"/threads/{t['id']}/snooze", json={"hours": 1})
    clock.advance(hours=3)
    # three ignored nudges: threshold is 2.5x a 24h rhythm = 60h; ~100h have passed
    assert len(client.get("/nudges").json()["nudges"]) == 1
    assert client.post(f"/threads/{t['id']}/snooze", json={"hours": 0}).status_code == 422


def test_pause_and_resume(client, clock):
    t = make(client, kind="book")
    clock.advance(days=4)
    until = (clock.now + timedelta(days=7)).isoformat()
    paused = client.post(f"/threads/{t['id']}/pause", json={"until": until}).json()
    assert paused["quiet"] and not paused["nudgeable"]
    assert client.get("/nudges").json()["nudges"] == []
    assert (
        client.post(f"/threads/{t['id']}/pause", json={"until": "2026-10-30T10:00:00"}).status_code
        == 422
    )
    resumed = client.post(f"/threads/{t['id']}/resume").json()
    assert resumed["nudgeable"] and resumed["paused_until"] is None


def test_update_and_clear_override(client):
    t = make(client, kind="book")
    r = client.patch(f"/threads/{t['id']}", json={"interval_hours": 100, "name": "Deep reading"})
    assert r.json()["interval_hours"] == 100 and r.json()["name"] == "Deep reading"
    r = client.patch(f"/threads/{t['id']}", json={"interval_hours": None})
    assert r.json()["interval_hours"] == 24  # back to the kind's rhythm


def test_soft_delete(client):
    t = make(client)
    assert client.delete(f"/threads/{t['id']}").status_code == 204
    assert client.get("/threads").json() == []
    assert client.post(f"/threads/{t['id']}/touch").status_code == 404
    assert client.delete(f"/threads/{t['id']}").status_code == 404


def test_nudge_budget_groups_the_rest(client, clock, monkeypatch):
    monkeypatch.setattr(config, "NUDGE_CAP", 2)
    for name in ("a", "b", "c", "d"):
        make(client, name, kind="book")
    clock.advance(days=5)
    body = client.get("/nudges").json()
    assert len(body["nudges"]) == 2 and body["grouped"] == 2
    assert body["summary"].startswith("2 more have gone quiet")
    assert body["nudges"][0]["message"].endswith("added 5 days ago, not touched yet")


def test_nudge_message_reads_gently(client, clock):
    t = make(client, "Book", kind="book")
    client.post(f"/threads/{t['id']}/touch")
    clock.advance(days=3)
    msg = client.get("/nudges").json()["nudges"][0]["message"]
    assert msg == "Book: last touched 3 days ago"


def test_no_nudges_in_quiet_hours_or_off_days(client, clock):
    make(client, "Work", kind="project", active_days=[0, 1, 2, 3, 4])
    clock.advance(days=5)  # Saturday midday
    assert client.get("/nudges").json()["nudges"] == []
    clock.advance(days=2)  # Monday midday
    assert len(client.get("/nudges").json()["nudges"]) == 1
    clock.advance(hours=10)  # 22:00 UTC = 00:00 Tuesday in Madrid: quiet hours
    assert client.get("/nudges").json()["nudges"] == []


@pytest.fixture
def sent():
    """Replaces the real ntfy publisher with a recorder; nothing touches the network."""
    messages = []
    app.dependency_overrides[get_publisher] = lambda: (
        lambda title, msg: messages.append((title, msg))
    )
    return messages


def test_send_publishes_each_nudge(client, clock, sent, monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "http://ntfy")
    t = make(client, "Book", kind="book")
    client.post(f"/threads/{t['id']}/touch")
    clock.advance(days=3)
    r = client.post("/nudges/send")
    assert r.status_code == 200 and r.json() == {"sent": 1}
    assert sent == [("Book", "Book: last touched 3 days ago")]


def test_send_adds_one_summary_for_the_rest(client, clock, sent, monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "http://ntfy")
    monkeypatch.setattr(config, "NUDGE_CAP", 1)
    for name in ("a", "b", "c"):
        make(client, name, kind="book")
    clock.advance(days=5)
    assert client.post("/nudges/send").json() == {"sent": 2}
    assert sent[1][0] == "More have gone quiet"


def test_send_with_nothing_due_sends_nothing(client, sent, monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "http://ntfy")
    make(client, "Book", kind="book")
    assert client.post("/nudges/send").json() == {"sent": 0}
    assert sent == []


def test_send_is_off_without_a_ntfy_url(client, sent, monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "")
    assert client.post("/nudges/send").status_code == 503
    assert sent == []


def test_send_reports_an_unreachable_ntfy(client, clock, monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "http://ntfy")

    def down(title, msg):
        raise ntfy.NtfyError("connection refused")

    app.dependency_overrides[get_publisher] = lambda: down
    make(client, "Book", kind="book")
    clock.advance(days=5)
    r = client.post("/nudges/send")
    assert r.status_code == 502 and "connection refused" in r.json()["detail"]


def test_touch_clears_the_backoff_built_up_by_snoozes(client, clock):
    t = make(client, kind="book")
    for _ in range(4):
        client.post(f"/threads/{t['id']}/snooze", json={"hours": 1})  # threshold now 4.5x = 108h
    clock.advance(hours=45)
    assert client.get("/nudges").json()["nudges"] == []  # 1.9x is below 4.5x
    client.post(f"/threads/{t['id']}/touch")
    clock.advance(hours=48)
    assert len(client.get("/nudges").json()["nudges"]) == 1  # back to 1.5x: 2.0x is quiet
