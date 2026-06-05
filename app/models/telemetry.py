"""Telemetry data models mirroring OBD-II / ECU signals."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GearState(str, Enum):
    """Simplified transmission state."""

    PARK = "P"
    NEUTRAL = "N"
    DRIVE = "D"


class Telemetry(BaseModel):
    """A single live snapshot of the vehicle's ECU signals.

    Field names and units follow common OBD-II PIDs so the data looks the
    same whether it comes from this simulator or a real adapter.
    """

    timestamp: datetime = Field(..., description="UTC time the frame was sampled")
    engine_running: bool = Field(..., description="Whether the engine is on")

    # Core powertrain
    rpm: float = Field(..., description="Engine speed (rev/min) — PID 0x0C")
    speed_kmh: float = Field(..., description="Vehicle speed (km/h) — PID 0x0D")
    throttle_pct: float = Field(..., description="Throttle position (%) — PID 0x11")
    engine_load_pct: float = Field(..., description="Calculated engine load (%) — PID 0x04")
    gear: GearState = Field(..., description="Transmission state")

    # Air / fuel
    maf_gps: float = Field(..., description="Mass air flow (g/s) — PID 0x10")
    intake_temp_c: float = Field(..., description="Intake air temperature (°C) — PID 0x0F")
    fuel_level_pct: float = Field(..., description="Fuel tank level (%) — PID 0x2F")
    fuel_rate_lph: float = Field(..., description="Instantaneous fuel consumption (L/h)")

    # Thermal
    coolant_temp_c: float = Field(..., description="Engine coolant temperature (°C) — PID 0x05")
    ambient_temp_c: float = Field(..., description="Ambient air temperature (°C) — PID 0x46")

    # Electrical / timing
    timing_advance_deg: float = Field(..., description="Ignition timing advance (°) — PID 0x0E")
    battery_voltage: float = Field(..., description="Control-module voltage (V) — PID 0x42")

    # Diagnostics
    odometer_km: float = Field(..., description="Cumulative distance travelled (km)")
    dtc: Optional[str] = Field(None, description="Active diagnostic trouble code, if any")


class PidInfo(BaseModel):
    """Description of one supported telemetry signal."""

    pid: str
    name: str
    unit: str


class FaultRequest(BaseModel):
    """Inject or clear a diagnostic trouble code for the agent to reason about."""

    code: Optional[str] = Field(
        None,
        description="DTC such as 'P0301' (cylinder 1 misfire). Null clears the fault.",
        examples=["P0301"],
    )
