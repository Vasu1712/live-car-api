"""Telemetry data models — the live car data contract.

The payload is grouped the way a fleet/agent pipeline consumes it: identity and
timestamp at the top, then powertrain, thermal/fluids, geospatial and
safety-behaviour blocks. Field names and units follow common OBD-II PIDs so the
data looks the same whether it comes from this simulator or a real adapter.
"""
from typing import Optional

from pydantic import BaseModel, Field


class VehicleState(BaseModel):
    engine_running: bool
    ignition_status: bool
    gear: str = Field(..., description="P | N | D | R")
    odometer_km: float
    battery_voltage: float = Field(..., description="Control-module voltage (V) — PID 0x42")


class Powertrain(BaseModel):
    rpm: float = Field(..., description="Engine speed (rev/min) — PID 0x0C")
    speed_kmh: float = Field(..., description="Vehicle speed (km/h) — PID 0x0D")
    throttle_pct: float = Field(..., description="Throttle position (%) — PID 0x11")
    engine_load_pct: float = Field(..., description="Calculated engine load (%) — PID 0x04")
    maf_gps: float = Field(..., description="Mass air flow (g/s) — PID 0x10")
    timing_advance_deg: float = Field(..., description="Ignition timing advance (°BTDC) — PID 0x0E")


class ThermalFluids(BaseModel):
    fuel_level_pct: float = Field(..., description="Fuel tank level (%) — PID 0x2F")
    fuel_rate_lph: float = Field(..., description="Instantaneous fuel consumption (L/h)")
    coolant_temp_c: float = Field(..., description="Engine coolant temperature (°C) — PID 0x05")
    ambient_temp_c: float = Field(..., description="Ambient air temperature (°C) — PID 0x46")
    intake_temp_c: float = Field(..., description="Intake air temperature (°C) — PID 0x0F")


class Geospatial(BaseModel):
    latitude: float
    longitude: float
    heading_deg: float = Field(..., description="Compass heading (0=N, 90=E, 180=S, 270=W)")


class SafetyBehavior(BaseModel):
    harsh_braking_flag: bool
    rapid_acceleration_flag: bool
    dtc: Optional[str] = Field(None, description="Active diagnostic trouble code, if any")


class Telemetry(BaseModel):
    """A single live frame of the vehicle's state."""

    car_id: str
    timestamp: str = Field(..., description="UTC ISO-8601 sample time")
    vehicle_state: VehicleState
    powertrain: Powertrain
    thermal_fluids: ThermalFluids
    geospatial: Geospatial
    safety_behavior: SafetyBehavior


class FaultRequest(BaseModel):
    """Inject or clear a diagnostic trouble code for the agent to reason about."""

    code: Optional[str] = Field(
        None,
        description="DTC such as 'P0301' (cylinder 1 misfire). Null clears the fault.",
        examples=["P0301"],
    )
