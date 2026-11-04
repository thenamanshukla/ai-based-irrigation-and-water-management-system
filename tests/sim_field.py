"""TEST ONLY. Simulated field node used by the test suite to exercise the real hub code.
It is never imported by the service, so it cannot put data into the real database."""
import math
import random
from datetime import datetime, timedelta
from irrigation import models as M

STEP_MIN = 5


class FieldSim:
    def __init__(self, cfg, start: datetime, seed: int = 7, faults=None):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.t = start
        self.theta = cfg.soil.theta_fc - 0.02
        self.tank_depth = cfg.tank.depth_m * 0.9
        self.pond_l = cfg.pond.capacity_l * 0.8
        self.valve_open = False
        self.valve_until = None
        self.faults = faults or {}          # {"clog": (start_day, end_day, factor), "leak": (start, end, lph)}
        self.start = start
        self._new_day()

    # ---------------- weather
    def _new_day(self):
        doy = self.t.timetuple().tm_yday
        base = 30 + 2.5 * math.sin(2 * math.pi * (doy - 100) / 365)
        self.day_tmax = base + self.rng.gauss(0, 1.5)
        self.day_tmin = self.day_tmax - 9 + self.rng.gauss(0, 1.2)
        self.rain_today_mm = self.rng.choice([0] * 6 + [self.rng.uniform(4, 25)])
        self.rain_hour = self.rng.randint(13, 18)
        doy_i = self.t.timetuple().tm_yday
        dap = (self.t - self.start).days + 1
        et0 = M.et0_hargreaves(self.day_tmax, self.day_tmin, self.cfg.site.latitude_deg, doy_i)
        self.day_etc = M.etc(et0, M.crop_coefficient(self.cfg.crop, dap))

    def air_temp(self):
        h = self.t.hour + self.t.minute / 60
        frac = (math.sin(2 * math.pi * (h - 9) / 24) + 1) / 2   # min near 03:00, max near 15:00
        return self.day_tmin + (self.day_tmax - self.day_tmin) * frac + self.rng.gauss(0, 0.2)

    def raining(self):
        return self.rain_today_mm > 0 and self.rain_hour <= self.t.hour < self.rain_hour + 2

    # ---------------- faults
    def _active(self, name):
        if name not in self.faults:
            return None
        start, end, value = self.faults[name]
        day = (self.t - self.start).days
        return value if start <= day < end else None

    # ---------------- valve (commanded by the hub, protected by firmware rules)
    def command_valve(self, minutes: float):
        if minutes > 0:
            self.valve_open = True
            self.valve_until = self.t + timedelta(minutes=minutes)

    def _firmware_failsafe(self, raining):
        cfg = self.cfg
        tank_l = M.tank_volume_l(self.tank_depth, cfg.tank_area_m2)
        if self.valve_open and (raining or self.theta >= cfg.soil.theta_fc
                                or tank_l <= cfg.tank.reserve_l or self.t >= self.valve_until):
            self.valve_open = False

    # ---------------- physics step
    def step(self) -> dict:
        cfg, dt_h = self.cfg, STEP_MIN / 60
        if self.t.hour == 0 and self.t.minute == 0:
            self._new_day()
        raining = self.raining()
        self._firmware_failsafe(raining)

        # evapotranspiration spread over daylight hours
        h = self.t.hour + self.t.minute / 60
        if 6 <= h < 18:
            et_mm = self.day_etc * (math.pi / 24) * math.sin(math.pi * (h - 6) / 12) * dt_h
            self.theta -= et_mm / (1000 * cfg.crop.root_depth_m)

        # rain on soil and into the pond
        if raining:
            mm = self.rain_today_mm / 2 * dt_h
            self.theta += mm / (1000 * cfg.crop.root_depth_m)
            self.pond_l = min(cfg.pond.capacity_l, self.pond_l + mm * cfg.pond.catchment_m2 * cfg.pond.runoff_coeff)

        # valve flow from the header tank
        if self.valve_open:
            head = M.head_m(self.tank_depth, cfg.tank)
            flow = cfg.emitters.count * M.emitter_flow_lph(head, cfg.emitters)
            flow *= self._active("clog") or 1.0
            leak = self._active("leak") or 0.0
            out_l = min((flow + leak) * dt_h, M.tank_volume_l(self.tank_depth, cfg.tank_area_m2))
            to_soil_l = out_l * flow / (flow + leak) * cfg.emitters.efficiency if flow + leak else 0
            self.tank_depth -= out_l / (cfg.tank_area_m2 * 1000)
            self.theta += to_soil_l / (cfg.zone.area_m2 * 1000 * cfg.crop.root_depth_m)
        else:
            # farmer or float valve tops up the header tank from the pond
            tank_l = M.tank_volume_l(self.tank_depth, cfg.tank_area_m2)
            if tank_l < 0.5 * cfg.tank.capacity_l and self.pond_l > 0:
                add = min(cfg.tank.capacity_l * 0.95 - tank_l, self.pond_l)
                self.pond_l -= add
                self.tank_depth += add / (cfg.tank_area_m2 * 1000)

        # drainage above field capacity
        self.theta = max(cfg.soil.theta_wp * 0.8, min(self.theta, cfg.soil.theta_fc + 0.02))
        if self.theta > cfg.soil.theta_fc:
            self.theta -= 0.25 * (self.theta - cfg.soil.theta_fc)

        packet = self.packet(raining)
        self.t += timedelta(minutes=STEP_MIN)
        return packet

    def packet(self, raining) -> dict:
        """Same fields as the real radio packet; sensor noise included."""
        cfg = self.cfg
        ir_distance = cfg.tank.sensor_to_floor_m - self.tank_depth + self.rng.gauss(0, 0.002)
        return {
            "ts": self.t.strftime("%Y-%m-%d %H:%M"), "node": "A",
            "moisture": round(100 * (self.theta + self.rng.gauss(0, 0.003)), 2),
            "soil_temp": round(self.air_temp() - 3, 1), "ec": 450, "ph": 6.5, "n": 40, "p": 25, "k": 120,
            "rain": int(raining), "tank_cm": round(ir_distance * 100, 2),
            "air_temp": round(self.air_temp(), 1), "air_rh": 65, "valve": int(self.valve_open),
        }

    def stress_prob(self) -> float:
        """Stand-in for the IMX500 water stress classifier output."""
        taw = M.taw_mm(self.cfg.soil, self.cfg.crop)
        rel = M.depletion_mm(self.theta, self.cfg.soil, self.cfg.crop) / taw
        return 1 / (1 + math.exp(-14 * (rel - 0.55)))
