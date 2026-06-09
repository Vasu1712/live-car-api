"""Vehicle telemetry simulator.

Mimics the raw ECU + GPS data a connected car would emit when no physical OBD
adapter is present. A virtual driver continuously picks speed targets and
accelerates, cruises and brakes toward them; every other signal (RPM, load,
fuel burn, position, ...) is derived from that motion so the stream stays
internally consistent and physically plausible — unlike independent per-signal
noise, which produces impossible states (e.g. 95% throttle at idle RPM).

State advances against the wall clock, so every read reflects "now", making the
output a drop-in stand-in for a live feed.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from datetime import datetime, timezone

CAR_ID = "car_fleet_nissan_9842"

# --- Vehicle constants (roughly a small petrol hatchback) ----------------------
IDLE_RPM = 800.0
MAX_RPM = 6500.0
MAX_SPEED_KMH = 160.0
# rpm per km/h, per gear (1..6) — tuned so each gear spans ~1200–2600 rpm.
GEAR_RATIOS = [144.0, 100.0, 70.0, 49.0, 34.0, 24.0]
UPSHIFT_RPM = 2600.0
DOWNSHIFT_RPM = 1200.0
LAUNCH_RPM = 2600.0          # extra revs available on full throttle (converter slip)
TANK_LITRES = 45.0
OPERATING_COOLANT_C = 90.0

# Thresholds for harsh-event flags (km/h per second; ~0.4 g ≈ 14 km/h/s).
RAPID_ACCEL_KMHS = 8.0
HARSH_BRAKE_KMHS = -10.0


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 with a trailing 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class VehicleSimulator:
    """Stateful, time-driven model of a single vehicle's telemetry."""

    def __init__(self, ambient_c: float = 22.0, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._lock = asyncio.Lock()

        # Externally controllable state
        self.engine_running = True
        self.ignition_on = True
        self.dtc: str | None = None
        self.ambient_c = ambient_c

        # Internal physical state
        self._now = time.monotonic()
        self._speed = 0.0            # km/h
        self._accel = 0.0            # km/h per second, last tick
        self._target_speed = 0.0     # km/h the virtual driver is aiming for
        self._target_hold = 0.0      # seconds left before picking a new target
        self._gear = 1
        self._throttle = 0.0         # 0..100 %
        # Warm start: a live, driven car is already at operating temperature.
        self._coolant = 88.0
        self._fuel_pct = 72.0
        self._odometer = 12450.0     # km on the clock

        # Geospatial state (starts near Gurugram, India).
        self._lat = 28.4595
        self._lon = 77.0266
        self._heading = 180.0        # degrees, 0=N

    # -- Driver behaviour -------------------------------------------------------
    def _pick_target(self) -> None:
        """Choose the next cruise target and how long to hold it."""
        roll = self._rng.random()
        if roll < 0.25:
            self._target_speed = 0.0                         # come to a stop
        elif roll < 0.55:
            self._target_speed = self._rng.uniform(30, 60)   # city
        else:
            self._target_speed = self._rng.uniform(70, 120)  # open road
        self._target_hold = self._rng.uniform(6.0, 20.0)
        # A new leg usually means a turn.
        self._heading = (self._heading + self._rng.uniform(-40, 40)) % 360.0

    # -- Core update ------------------------------------------------------------
    def _advance(self, dt: float) -> None:
        """Advance internal state by ``dt`` seconds."""
        if not self.engine_running:
            self._speed = 0.0
            self._throttle = 0.0
            self._accel = 0.0
            # Coolant slowly bleeds back toward ambient when off.
            self._coolant += (self.ambient_c - self._coolant) * min(1.0, dt / 600.0)
            return

        # Decide where the driver is headed.
        self._target_hold -= dt
        if self._target_hold <= 0:
            self._pick_target()

        # Accelerate or brake toward the target speed.
        error = self._target_speed - self._speed
        if error > 0.5:
            accel = min(12.0, error)          # km/h per second (eased near target)
            self._throttle = min(95.0, 20.0 + error * 1.5)
        elif error < -0.5:
            accel = max(-18.0, error)         # braking is stronger than accel
            self._throttle = 0.0
        else:
            accel = 0.0
            self._throttle = 8.0 + self._speed * 0.12  # steady-state hold

        self._accel = accel
        self._speed = max(0.0, min(MAX_SPEED_KMH, self._speed + accel * dt))

        # Gearbox: shift on RPM thresholds.
        self._select_gear()

        # Distance, position, fuel, odometer.
        dist_km = self._speed * dt / 3600.0
        self._odometer += dist_km
        self._advance_position(dist_km, dt)
        self._fuel_pct = max(
            0.0, self._fuel_pct - self._fuel_rate_lph() * dt / 3600.0 / TANK_LITRES * 100.0
        )

        # Coolant holds at operating temperature, climbing faster under load.
        warm = (0.04 + self.engine_load / 100.0 * 0.05) * dt
        self._coolant += (OPERATING_COOLANT_C - self._coolant) * min(1.0, warm)

    def _advance_position(self, dist_km: float, dt: float) -> None:
        """Move lat/lon along the current heading and let the heading drift."""
        if self._speed > 5.0:
            self._heading = (self._heading + self._rng.uniform(-8, 8) * dt) % 360.0
        hr = math.radians(self._heading)
        self._lat += (dist_km / 111.0) * math.cos(hr)
        self._lon += (dist_km / (111.0 * math.cos(math.radians(self._lat)))) * math.sin(hr)

    def _select_gear(self) -> None:
        if self._speed < 1.0:
            self._gear = 1
            return
        road_rpm = self._speed * GEAR_RATIOS[self._gear - 1]
        if road_rpm > UPSHIFT_RPM and self._gear < len(GEAR_RATIOS):
            self._gear += 1
        elif road_rpm < DOWNSHIFT_RPM and self._gear > 1:
            self._gear -= 1

    # -- Derived signals --------------------------------------------------------
    @property
    def rpm(self) -> float:
        """Engine speed — the greater of road demand and throttle-driven revs.

        Flooring the throttle from a standstill revs the engine immediately
        (torque-converter slip) rather than waiting for the car to gain speed,
        so RPM tracks throttle even when ``speed_kmh`` is still near zero.
        """
        if not self.engine_running:
            return 0.0
        road_rpm = self._speed * GEAR_RATIOS[self._gear - 1] if self._speed >= 1.0 else 0.0
        launch_rpm = IDLE_RPM + (self._throttle / 100.0) * LAUNCH_RPM
        rpm = max(IDLE_RPM, road_rpm, launch_rpm)
        if self._speed < 1.0 and self._throttle < 5.0:
            rpm = IDLE_RPM + math.sin(time.monotonic() * 3) * 30  # idle wobble
        return min(MAX_RPM, rpm)

    @property
    def engine_load(self) -> float:
        """Calculated load (%) — climbs with throttle and rpm."""
        if not self.engine_running:
            return 0.0
        base = 18.0 if self._speed < 1.0 else 25.0
        return min(100.0, base + self._throttle * 0.6 + (self.rpm / MAX_RPM) * 20.0)

    def _fuel_rate_lph(self) -> float:
        if not self.engine_running:
            return 0.0
        return 0.8 + self.engine_load / 100.0 * (self.rpm / 1000.0) * 2.2

    @property
    def maf(self) -> float:
        if not self.engine_running:
            return 0.0
        return 2.0 + self.engine_load / 100.0 * (self.rpm / 1000.0) * 6.5

    @property
    def gear_label(self) -> str:
        if not self.engine_running:
            return "P"
        return "D" if self._speed >= 1.0 else "N"

    # -- Public API -------------------------------------------------------------
    async def sample(self) -> dict:
        """Advance to the current instant and return a flat snapshot of state."""
        async with self._lock:
            now = time.monotonic()
            dt = min(now - self._now, 5.0)  # clamp long gaps so state stays sane
            self._now = now
            self._advance(dt)
            return self._snapshot()

    def _snapshot(self) -> dict:
        running = self.engine_running
        load = self.engine_load
        return {
            "car_id": CAR_ID,
            "timestamp": _now_iso(),
            # vehicle_state
            "engine_running": running,
            "ignition_status": self.ignition_on,
            "gear": self.gear_label,
            "odometer_km": round(self._odometer, 1),
            "battery_voltage": round((13.7 + math.sin(time.monotonic()) * 0.3) if running else 12.4, 2),
            # powertrain
            "rpm": round(self.rpm, 1),
            "speed_kmh": round(self._speed, 1),
            "throttle_pct": round(self._throttle, 1),
            "engine_load_pct": round(load, 1),
            "maf_gps": round(self.maf, 2),
            "timing_advance_deg": round(10.0 + (self.rpm / MAX_RPM) * 28.0, 1) if running else 0.0,
            # thermal_fluids
            "fuel_level_pct": round(self._fuel_pct, 1),
            "fuel_rate_lph": round(self._fuel_rate_lph(), 2),
            "coolant_temp_c": round(self._coolant, 1),
            "ambient_temp_c": round(self.ambient_c, 1),
            "intake_temp_c": round(self.ambient_c + load / 100.0 * 30.0, 1),
            # geospatial
            "latitude": round(self._lat, 6),
            "longitude": round(self._lon, 6),
            "heading_deg": round(self._heading, 1),
            # safety_behavior
            "harsh_braking_flag": running and self._accel <= HARSH_BRAKE_KMHS,
            "rapid_acceleration_flag": running and self._accel >= RAPID_ACCEL_KMHS,
            "dtc": self.dtc,
        }

    async def set_engine(self, running: bool) -> None:
        async with self._lock:
            self.engine_running = running

    async def set_fault(self, code: str | None) -> None:
        async with self._lock:
            self.dtc = code


# Module-level singleton — one virtual car shared across requests/streams.
simulator = VehicleSimulator()
