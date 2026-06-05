"""Integration tests for the live SSE and WebSocket telemetry streams.

These run against a real uvicorn server in a subprocess. The streaming
endpoints are unbounded, which the in-process Starlette TestClient cannot
cancel, so a genuine ASGI server is required to exercise them faithfully.
"""
import asyncio
import json
import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server() -> str:
    """Boot uvicorn on a free port; yield the base URL; tear it down."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("uvicorn did not start in time")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_sse_stream_emits_frames(server: str):
    """The SSE feed pushes well-formed JSON telemetry frames."""
    with httpx.stream("GET", f"{server}/telemetry/stream", params={"hz": 20}, timeout=5) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        for line in resp.iter_lines():
            if line.startswith("data: "):
                frame = json.loads(line[len("data: "):])
                assert "rpm" in frame and "speed_kmh" in frame
                break  # disconnecting here should stop the server-side generator


def test_websocket_pushes_frames(server: str):
    """The WebSocket feed pushes telemetry frames until the client leaves."""
    import websockets  # bundled with uvicorn[standard]

    ws_url = server.replace("http://", "ws://") + "/telemetry/ws?hz=20"

    async def _read_one() -> dict:
        async with websockets.connect(ws_url) as ws:
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

    frame = asyncio.run(_read_one())
    assert "rpm" in frame
    assert "timestamp" in frame
