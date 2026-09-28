"""Tests for simulator scenarios and the UI → control file → generator path."""

import json
import time

from fastapi.testclient import TestClient

from simulator.generate_logs import _apply_scenario, _check_control


def test_scenarios_shape_error_and_volume():
    assert _apply_scenario("spike", 0.02, 0.35, 5, 60) == (0.35, 1.0)
    err, mult = _apply_scenario("ramp", 0.02, 0.35, 30, 60)
    assert 0.02 < err < 0.35 and mult == 1.0
    assert _apply_scenario("flood", 0.02, 0.35, 5, 60)[1] == 10.0
    assert _apply_scenario("outage", 0.02, 0.35, 10, 60) == (0.95, 1.0)
    assert _apply_scenario("outage", 0.02, 0.35, 50, 60)[1] == 0.0  # silence after 70%


def test_control_file_drives_scenario_then_expires(tmp_path):
    ctl = tmp_path / "sim_control.json"
    ctl.write_text(json.dumps({"action": "spike", "scenario": "flood", "error_ratio": 0.35,
                               "duration_sec": 60, "started_at": time.time()}))
    assert _check_control(ctl, 0.02, 0.35)[1] == 10.0

    ctl.write_text(json.dumps({"action": "spike", "duration_sec": 1, "started_at": time.time() - 5}))
    assert _check_control(ctl, 0.02, 0.35) is None
    assert json.loads(ctl.read_text())["action"] == "recover"


def test_control_file_missing_or_corrupt_is_ignored(tmp_path):
    ctl = tmp_path / "sim_control.json"
    assert _check_control(ctl, 0.02, 0.35) is None
    ctl.write_text("{half-written")
    assert _check_control(ctl, 0.02, 0.35) is None


def _client(monkeypatch, tmp_path, enable_sim=True):
    monkeypatch.setenv("LOG_FILE_PATH", str(tmp_path / "logs" / "app.log"))
    monkeypatch.setenv("ENABLE_SIM", str(enable_sim).lower())
    from app.main import create_app
    return TestClient(create_app())  # no `with`: lifespan (tailers) not started


def test_sim_endpoint_writes_control_next_to_log(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post("/api/sim/spike", json={"scenario": "outage", "duration_sec": 30})
    assert r.status_code == 200
    ctl = json.loads((tmp_path / "logs" / "sim_control.json").read_text())
    assert ctl["scenario"] == "outage" and ctl["duration_sec"] == 30


def test_sim_endpoint_rejects_bad_input_and_respects_flag(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.post("/api/sim/spike", json={"scenario": "nuke"}).status_code == 422
    assert client.post("/api/sim/spike", json={"error_ratio": 2}).status_code == 422
    disabled = _client(monkeypatch, tmp_path, enable_sim=False)
    assert disabled.post("/api/sim/spike", json={}).status_code == 403
