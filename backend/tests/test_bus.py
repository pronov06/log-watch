"""Tests for the event bus: seq cursor, boot id, alert patches, backpressure."""

from app.bus import EventBus


def test_since_returns_only_newer_envelopes():
    bus = EventBus(ring_size=10)
    for i in range(5):
        bus.publish("metric", {"i": i})
    envs, latest = bus.since(3)
    assert [e.seq for e in envs] == [4, 5]
    assert latest == 5


def test_boot_id_differs_per_instance():
    assert EventBus().boot_id != EventBus().boot_id


def test_update_alert_patches_store_and_broadcasts():
    bus = EventBus()
    q = bus.subscribe()
    bus.publish("alert", {"id": "a1", "key": "k", "status": "OPEN"})
    patch = bus.update_alert("a1", {"acknowledged": True, "acknowledged_by": "me"})

    assert patch == {"id": "a1", "acknowledged": True, "acknowledged_by": "me"}
    assert bus.get_alerts()[0]["acknowledged"] is True
    types = [q.get_nowait().type for _ in range(q.qsize())]
    assert types == ["alert", "alert_update"]


def test_update_alert_unknown_id_returns_none():
    assert EventBus().update_alert("missing", {"acknowledged": True}) is None


def test_full_client_queue_drops_non_alert_first():
    bus = EventBus()
    q = bus.subscribe(maxsize=2)
    bus.publish("alert", {"id": "a"})
    bus.publish("metric", {})
    bus.publish("alert", {"id": "b"})  # queue full → oldest non-alert dropped
    kept = [q.get_nowait().type for _ in range(q.qsize())]
    assert kept == ["alert", "alert"]
