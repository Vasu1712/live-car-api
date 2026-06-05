"""Vehicle telemetry simulator.

Mimics the raw ECU data an OBD-II adapter would pull from a moving car when no
physical hardware is connected. A virtual driver continuously picks speed
targets and accelerates, cruises and brakes toward them; the rest of the
signals (RPM, load, fuel burn, coolant warm-up, ...) are derived from that
motion so the stream stays internally consistent and physically plausible.

State advances against the wall clock, so every read reflects "now" — making
the output a drop-in stand-in for a live feed.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from datetime import datetime, timezone

from app.models.telemetry import GearState, Telemetry

# --- Vehicle constants (roughly a small petrol hatchback) ----------------------
IDLE_RPM = 800.0
MAX_RPM = 6500.0
MAX_SPEED_KMH = 160.0
GEAR_RATIOS = [13.0, 7.6, 5.2, 3.9, 3.1, 2.6]  # rpm per km/h, per gear (1..6)
UPSHIFT_RPM = 2600.0
DOWNSHIFT_RPM = 1200.0
TANK_LITRES = 45.0
OPERATING_COOLANT_C = 90.0


class VehicleSimulator:
    """Stateful, time-driven model of a single vehicle's telemetry."""

    def __init__(self, ambient_c: float = 22.0, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._lock = asyncio.Lock()

        # Externally controllable state
        self.engine_running = True
        self.dtc: str | None = None
        self.ambient_c = ambient_c

        # Internal physical state
        self._now = time.monotonic()
        self._speed = 0.0            # km/h
        self._target_speed = 0.0     # km/h the virtual driver is aiming for
        self._target_hold = 0.0      # seconds left before picking a new target
        self._gear = 1
        self._throttle = 0.0         # 0..100 %
        self._coolant = ambient_c    # starts cold, warms to OPERATING_COOLANT_C
        self._fuel_pct = 72.0
        self._odometer = 12450.0     # km on the clock

    # -- Driver behaviour -------------------------------------------------------
    def _pick_target(self) -> None:
        """Choose the next cruise target and how long to hold it."""
        roll = self._rng.random()
        if roll < 0.25:
            self._target_speed = 0.0                       # come to a stop
        elif roll < 0.55:
            self._target_speed = self._rng.uniform(30, 60)  # city
        else:
            self._target_speed = self._rng.uniform(70, 120)  # open road
        self._target_hold = self._rng.uniform(6.0, 20.0)

    # -- Core update ------------------------------------------------------------
    def _advance(self, dt: float) -> None:
        """Advance internal state by ``dt`` seconds."""
        if not self.engine_running:
            self._speed = 0.0
            self._throttle = 0.0
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

        self._speed = max(0.0, min(MAX_SPEED_KMH, self._speed + accel * dt))

        # Gearbox: shift on RPM thresholds.
        self._select_gear()

        # Fuel burn & odometer.
        dist_km = self._speed * dt / 3600.0
        self._odometer += dist_km
        self._fuel_pct = max(0.0, self._fuel_pct - self._fuel_rate_lph() * dt / 3600.0 / TANK_LITRES * 100.0)

        # Coolant warms toward operating temperature, faster under load.
        warm_rate = (0.04 + self.engine_load / 100.0 * 0.05) * dt
        self._coolant += (OPERATING_COOLANT_C - self._coolant) * min(1.0, warm_rate)

    def _select_gear(self) -> None:
        if self._speed < 1.0:
            self._gear = 1
            return
        rpm = self._speed * GEAR_RATIOS[self._gear - 1]
        if rpm > UPSHIFT_RPM and self._gear < len(GEAR_RATIOS):
            self._gear += 1
        elif rpm < DOWNSHIFT_RPM and self._gear > 1:
            self._gear -= 1

    # -- Derived signals --------------------------------------------------------
    @property
    def rpm(self) -> float:
        if not self.engine_running:
            return 0.0
        if self._speed < 1.0:
            # Idle with a little natural wobble.
            return IDLE_RPM + math.sin(time.monotonic() * 3) * 30
        return min(MAX_RPM, self._speed * GEAR_RATIOS[self._gear - 1])

    @property
    def engine_load(self) -> float:
        """Calculated load (%) — climbs with throttle and rpm."""
        if not self.engine_running:
            return 0.0
        base = 18.0 if self._speed < 1.0 else 25.0
        return min(100.0, base + self._throttle * 0.6 + (self.rpm / MAX_RPM) * 20.0)

    def _fuel_rate_lph(self) -> float:
        """Instantaneous consumption (L/h)."""
        if not self.engine_running:
            return 0.0
        idle = 0.8
        return idle + self.engine_load / 100.0 * (self.rpm / 1000.0) * 2.2

    @property
    def maf(self) -> float:
        if not self.engine_running:
            return 0.0
        return 2.0 + self.engine_load / 100.0 * (self.rpm / 1000.0) * 4.5

    @property
    def gear_state(self) -> GearState:
        if not self.engine_running:
            return GearState.PARK
        return GearState.DRIVE if self._speed >= 1.0 else GearState.NEUTRAL

    # -- Public API -------------------------------------------------------------
    async def read(self) -> Telemetry:
        """Advance to the current instant and return a telemetry frame."""
        async with self._lock:
            now = time.monotonic()
            dt = min(now - self._now, 5.0)  # clamp long gaps so state stays sane
            self._now = now
            self._advance(dt)
            return self._frame()

    def _frame(self) -> Telemetry:
        return Telemetry(
            timestamp=datetime.now(timezone.utc),
            engine_running=self.engine_running,
            rpm=round(self.rpm, 1),
            speed_kmh=round(self._speed, 1),
            throttle_pct=round(self._throttle, 1),
            engine_load_pct=round(self.engine_load, 1),
            gear=self.gear_state,
            maf_gps=round(self.maf, 2),
            intake_temp_c=round(self.ambient_c + self.engine_load / 100.0 * 18.0, 1),
            fuel_level_pct=round(self._fuel_pct, 1),
            fuel_rate_lph=round(self._fuel_rate_lph(), 2),
            coolant_temp_c=round(self._coolant, 1),
            ambient_temp_c=round(self.ambient_c, 1),
            timing_advance_deg=round(10.0 + self._throttle * 0.15, 1),
            battery_voltage=round(13.9 + math.sin(time.monotonic()) * 0.2, 2),
            odometer_km=round(self._odometer, 2),
            dtc=self.dtc,
        )

    async def set_engine(self, running: bool) -> None:
        async with self._lock:
            self.engine_running = running

    async def set_fault(self, code: str | None) -> None:
        async with self._lock:
            self.dtc = code


# Module-level singleton — one virtual car shared across requests/streams.
simulator = VehicleSimulator()
