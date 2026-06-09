"""Live telemetry endpoints.

Exposes the simulated connected-car feed so an agentic pipeline can consume it:

* ``GET  /api/v1/telemetry``        — current live frame (grouped payload)
* ``WS   /ws/v1/telemetry/stream``  — same frames pushed continuously
* ``POST /api/v1/engine``           — key-on / key-off
* ``POST /api/v1/fault``            — inject / clear a DTC
"""
import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.models.telemetry import (
    FaultRequest,
    Geospatial,
    Powertrain,
    SafetyBehavior,
    Telemetry,
    ThermalFluids,
    VehicleState,
)
from app.simulator import simulator

router = APIRouter(tags=["telemetry"])


def _build(sample: dict) -> Telemetry:
    """Assemble the grouped telemetry payload from a flat simulator sample."""
    return Telemetry(
        car_id=sample["car_id"],
        timestamp=sample["timestamp"],
        vehicle_state=VehicleState(
            engine_running=sample["engine_running"],
            ignition_status=sample["ignition_status"],
            gear=sample["gear"],
            odometer_km=sample["odometer_km"],
            battery_voltage=sample["battery_voltage"],
        ),
        powertrain=Powertrain(
            rpm=sample["rpm"],
            speed_kmh=sample["speed_kmh"],
            throttle_pct=sample["throttle_pct"],
            engine_load_pct=sample["engine_load_pct"],
            maf_gps=sample["maf_gps"],
            timing_advance_deg=sample["timing_advance_deg"],
        ),
        thermal_fluids=ThermalFluids(
            fuel_level_pct=sample["fuel_level_pct"],
            fuel_rate_lph=sample["fuel_rate_lph"],
            coolant_temp_c=sample["coolant_temp_c"],
            ambient_temp_c=sample["ambient_temp_c"],
            intake_temp_c=sample["intake_temp_c"],
        ),
        geospatial=Geospatial(
            latitude=sample["latitude"],
            longitude=sample["longitude"],
            heading_deg=sample["heading_deg"],
        ),
        safety_behavior=SafetyBehavior(
            harsh_braking_flag=sample["harsh_braking_flag"],
            rapid_acceleration_flag=sample["rapid_acceleration_flag"],
            dtc=sample["dtc"],
        ),
    )


@router.get("/api/v1/telemetry", response_model=Telemetry, summary="Live telemetry frame")
async def get_telemetry() -> Telemetry:
    """Return one full live frame, as a connected-car poll would."""
    return _build(await simulator.sample())


@router.websocket("/ws/v1/telemetry/stream")
async def stream_telemetry(ws: WebSocket, hz: float = 2.0) -> None:
    """Push telemetry frames over a WebSocket until the client disconnects."""
    hz = max(0.2, min(20.0, hz))
    interval = 1.0 / hz
    await ws.accept()
    try:
        while True:
            frame = _build(await simulator.sample())
            await ws.send_text(frame.model_dump_json())
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


@router.post("/api/v1/engine", response_model=Telemetry, summary="Start / stop the engine")
async def set_engine(running: bool = Query(..., description="True to start, False to stop")) -> Telemetry:
    """Toggle the engine so the agent can observe key-on / key-off transitions."""
    await simulator.set_engine(running)
    return _build(await simulator.sample())


@router.post("/api/v1/fault", response_model=Telemetry, summary="Inject / clear a DTC")
async def set_fault(req: FaultRequest) -> Telemetry:
    """Set an active diagnostic trouble code (or clear it with ``null``)."""
    await simulator.set_fault(req.code)
    return _build(await simulator.sample())
