"""Telemetry endpoint tests (non-streaming, via in-process TestClient)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_payload_shape_and_groups():
    """The frame carries all grouped blocks with plausible values."""
    body = client.get("/api/v1/telemetry").json()
    assert body["car_id"]
    for block in ("vehicle_state", "powertrain", "thermal_fluids", "geospatial", "safety_behavior"):
        assert block in body

    pt = body["powertrain"]
    assert 0 <= pt["rpm"] <= 6500
    assert 0 <= pt["speed_kmh"] <= 200
    assert body["vehicle_state"]["engine_running"] is True


def test_running_engine_is_warm_and_idles_above_stall():
    """A live, running engine is at operating temp and never below stall RPM."""
    body = client.get("/api/v1/telemetry").json()
    assert body["thermal_fluids"]["coolant_temp_c"] >= 80      # no cold-engine paradox
    assert body["powertrain"]["rpm"] >= 600                    # never below stall


def test_high_throttle_revs_the_engine():
    """RPM tracks throttle: high throttle must not read near idle (the RPM bug)."""
    # Sample repeatedly; whenever the virtual driver is hard on the throttle,
    # the engine must be revving well above idle — never stuck near stall.
    saw_high_throttle = False
    for _ in range(60):
        pt = client.get("/api/v1/telemetry").json()["powertrain"]
        if pt["throttle_pct"] >= 60:
            saw_high_throttle = True
            assert pt["rpm"] >= 2000, f"throttle {pt['throttle_pct']}% but rpm {pt['rpm']}"
    assert saw_high_throttle, "driver never opened the throttle — test inconclusive"


def test_engine_off_zeros_motion():
    """Stopping the engine parks the car and zeros powertrain signals."""
    try:
        body = client.post("/api/v1/engine", params={"running": False}).json()
        assert body["vehicle_state"]["engine_running"] is False
        assert body["vehicle_state"]["gear"] == "P"
        assert body["powertrain"]["rpm"] == 0
        assert body["powertrain"]["speed_kmh"] == 0
    finally:
        client.post("/api/v1/engine", params={"running": True})


def test_fault_inject_and_clear():
    try:
        body = client.post("/api/v1/fault", json={"code": "P0301"}).json()
        assert body["safety_behavior"]["dtc"] == "P0301"
    finally:
        cleared = client.post("/api/v1/fault", json={"code": None}).json()
        assert cleared["safety_behavior"]["dtc"] is None


# Note: the WebSocket stream is exercised in tests/test_streaming.py against a
# real uvicorn server — Starlette's in-process TestClient cannot cancel an
# unbounded streaming endpoint cleanly.
