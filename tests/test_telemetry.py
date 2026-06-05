"""Telemetry endpoint tests (non-streaming, via in-process TestClient)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_snapshot_shape_and_bounds():
    """A snapshot returns plausible, in-range ECU signals."""
    body = client.get("/telemetry").json()
    assert body["engine_running"] is True
    assert 0 <= body["rpm"] <= 7000
    assert 0 <= body["speed_kmh"] <= 200
    assert 0 <= body["throttle_pct"] <= 100
    assert 0 <= body["fuel_level_pct"] <= 100
    assert body["dtc"] is None


def test_pids_listed():
    pids = client.get("/telemetry/pids").json()
    names = {p["name"] for p in pids}
    assert {"rpm", "speed_kmh", "coolant_temp_c"} <= names


def test_engine_off_zeros_motion():
    """Stopping the engine parks the car and zeros powertrain signals."""
    try:
        body = client.post("/telemetry/engine", params={"running": False}).json()
        assert body["engine_running"] is False
        assert body["rpm"] == 0
        assert body["speed_kmh"] == 0
        assert body["gear"] == "P"
    finally:
        client.post("/telemetry/engine", params={"running": True})


def test_fault_inject_and_clear():
    try:
        body = client.post("/telemetry/fault", json={"code": "P0301"}).json()
        assert body["dtc"] == "P0301"
    finally:
        cleared = client.post("/telemetry/fault", json={"code": None}).json()
        assert cleared["dtc"] is None


# Note: the infinite SSE/WebSocket streams are exercised in
# tests/test_streaming.py against a real uvicorn server. Starlette's in-process
# TestClient cannot cancel an unbounded streaming response, so it is unsuitable
# for those endpoints.
