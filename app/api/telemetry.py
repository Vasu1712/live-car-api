"""Live telemetry endpoints.

Exposes the simulated ECU feed in three shapes so an agentic pipeline can
consume it whichever way is convenient:

* ``GET  /telemetry``         — a single live snapshot
* ``GET  /telemetry/stream``  — Server-Sent Events, one frame per interval
* ``WS   /telemetry/ws``      — WebSocket push of the same frames
"""
import asyncio
import json

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.models.telemetry import FaultRequest, PidInfo, Telemetry
from app.simulator import simulator

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# Supported signals, advertised like a real adapter's PID scan.
SUPPORTED_PIDS = [
    PidInfo(pid="0x04", name="engine_load_pct", unit="%"),
    PidInfo(pid="0x05", name="coolant_temp_c", unit="°C"),
    PidInfo(pid="0x0C", name="rpm", unit="rev/min"),
    PidInfo(pid="0x0D", name="speed_kmh", unit="km/h"),
    PidInfo(pid="0x0E", name="timing_advance_deg", unit="°"),
    PidInfo(pid="0x0F", name="intake_temp_c", unit="°C"),
    PidInfo(pid="0x10", name="maf_gps", unit="g/s"),
    PidInfo(pid="0x11", name="throttle_pct", unit="%"),
    PidInfo(pid="0x2F", name="fuel_level_pct", unit="%"),
    PidInfo(pid="0x42", name="battery_voltage", unit="V"),
    PidInfo(pid="0x46", name="ambient_temp_c", unit="°C"),
]

# Bounds for the streaming sample rate (Hz).
_MIN_HZ = 0.2
_MAX_HZ = 20.0


@router.get("", response_model=Telemetry, summary="Current telemetry snapshot")
async def get_telemetry() -> Telemetry:
    """Read one live frame, exactly as an OBD poll would return."""
    return await simulator.read()


@router.get("/pids", response_model=list[PidInfo], summary="Supported signals")
async def list_pids() -> list[PidInfo]:
    """List the telemetry signals this feed exposes."""
    return SUPPORTED_PIDS


@router.get("/stream", summary="Live telemetry as Server-Sent Events")
async def stream_telemetry(
    request: Request,
    hz: float = Query(1.0, ge=_MIN_HZ, le=_MAX_HZ, description="Frames per second"),
) -> StreamingResponse:
    """Continuously push telemetry frames as SSE (`text/event-stream`).

    Each event's ``data:`` is a JSON telemetry frame — ideal for feeding an
    agent loop without managing a socket. The generator stops as soon as the
    client disconnects, so dropped consumers don't leak tasks.
    """
    interval = 1.0 / hz

    async def event_source():
        while not await request.is_disconnected():
            frame = await simulator.read()
            yield f"data: {frame.model_dump_json()}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.websocket("/ws")
async def telemetry_ws(websocket: WebSocket, hz: float = 1.0) -> None:
    """Stream telemetry frames over a WebSocket until the client disconnects."""
    hz = max(_MIN_HZ, min(_MAX_HZ, hz))
    interval = 1.0 / hz
    await websocket.accept()
    try:
        while True:
            frame = await simulator.read()
            await websocket.send_text(frame.model_dump_json())
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


@router.post("/engine", response_model=Telemetry, summary="Start/stop the engine")
async def set_engine(running: bool = Query(..., description="True to start, False to stop")) -> Telemetry:
    """Toggle the engine so the agent can observe key-on / key-off transitions."""
    await simulator.set_engine(running)
    return await simulator.read()


@router.post("/fault", response_model=Telemetry, summary="Inject or clear a DTC")
async def set_fault(req: FaultRequest) -> Telemetry:
    """Set an active diagnostic trouble code (or clear it with ``null``)."""
    await simulator.set_fault(req.code)
    return await simulator.read()
