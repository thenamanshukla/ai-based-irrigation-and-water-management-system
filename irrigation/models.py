"""Core equations (numbered as in the system working document)."""
import math
from dataclasses import dataclass

# ---------------------------------------------------------------- Eq. (1), (2)

def extraterrestrial_radiation_mm(lat_deg: float, day_of_year: int) -> float:
    """Ra in mm/day of evaporation equivalent (FAO-56 Eq. 21, x 0.408)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    gsc = 0.0820  # MJ m-2 min-1
    ra_mj = (24 * 60 / math.pi) * gsc * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    return 0.408 * ra_mj


def et0_hargreaves(t_max: float, t_min: float, lat_deg: float, day_of_year: int) -> float:
    """Reference evapotranspiration, mm/day. Eq. (1)."""
    if t_max < t_min:
        t_max, t_min = t_min, t_max
    ra = extraterrestrial_radiation_mm(lat_deg, day_of_year)
    t_mean = (t_max + t_min) / 2
    return max(0.0, 0.0023 * ra * (t_mean + 17.8) * math.sqrt(t_max - t_min))


def crop_coefficient(crop, day_after_planting: int) -> float:
    """FAO-56 piecewise linear Kc curve."""
    ini, dev, mid, late = crop.stage_days
    d = day_after_planting
    if d <= ini:
        return crop.kc_ini
    if d <= ini + dev:
        return crop.kc_ini + (crop.kc_mid - crop.kc_ini) * (d - ini) / dev
    if d <= ini + dev + mid:
        return crop.kc_mid
    if d <= ini + dev + mid + late:
        return crop.kc_mid + (crop.kc_end - crop.kc_mid) * (d - ini - dev - mid) / late
    return crop.kc_end


def etc(et0: float, kc: float) -> float:
    """Crop water demand, mm/day. Eq. (2)."""
    return kc * et0

# ---------------------------------------------------------------- Eq. (3)

def taw_mm(soil, crop) -> float:
    return 1000 * (soil.theta_fc - soil.theta_wp) * crop.root_depth_m


def depletion_mm(theta: float, soil, crop) -> float:
    return max(0.0, 1000 * (soil.theta_fc - theta) * crop.root_depth_m)


def forecast_theta(theta: float, etc_mm_per_day: float, crop, hours: float, rain_mm: float = 0.0, soil=None) -> float:
    """Physics baseline forecast of soil moisture after `hours`.
    Replaced by a LightGBM model once real field data has been collected."""
    change = (rain_mm - etc_mm_per_day * hours / 24) / (1000 * crop.root_depth_m)
    t = theta + change
    if soil is not None:
        t = min(t, soil.theta_fc)
    return t

# ---------------------------------------------------------------- Eq. (4), (5)

def tank_depth_from_ir(distance_m: float, tank) -> float:
    """Water depth h from IR distance d: h = sensor_to_floor - d."""
    return max(0.0, min(tank.depth_m, tank.sensor_to_floor_m - distance_m))


def tank_volume_l(depth_m: float, tank_area_m2: float) -> float:
    return depth_m * tank_area_m2 * 1000


def head_m(depth_m: float, tank) -> float:
    """H = z0 + h. Eq. (4)."""
    return tank.floor_above_emitters_m + depth_m


def emitter_flow_lph(head: float, em) -> float:
    """q = k H^x per emitter, litres per hour. Eq. (4)."""
    return em.k_lph * max(head, 0.0) ** em.x


def irrigation_minutes(net_depth_mm: float, area_m2: float, head: float, em) -> float:
    """t = A In / (eta N k H^x). Eq. (5). 1 mm over 1 m2 = 1 litre."""
    zone_flow = em.efficiency * em.count * emitter_flow_lph(head, em)
    if zone_flow <= 0:
        return float("inf")
    return 60 * (net_depth_mm * area_m2) / zone_flow

# ---------------------------------------------------------------- Eq. (6)

@dataclass
class FaultState:
    sigma_lph: float = 0.0
    calibrated: bool = False
    streak_high: int = 0
    streak_low: int = 0


class FaultDetector:
    """Residual r = Q_obs - N k H^x while the valve is open."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.state = FaultState()
        self._calib = []

    def to_state(self) -> dict:
        return {"calib": self._calib[-50:], "sigma": self.state.sigma_lph, "calibrated": self.state.calibrated}

    def load_state(self, s: dict | None):
        if s:
            self._calib = list(s.get("calib", []))
            self.state.sigma_lph = s.get("sigma", 0.0)
            self.state.calibrated = s.get("calibrated", False)

    def reset_streaks(self):
        self.state.streak_high = self.state.streak_low = 0

    def expected_lph(self, head):
        return self.cfg.emitters.count * emitter_flow_lph(head, self.cfg.emitters)

    def calibrate(self, observed_lph, head):
        """Feed residuals from known-good runs (commissioning)."""
        self._calib.append(observed_lph - self.expected_lph(head))
        if len(self._calib) >= 10:
            n = len(self._calib)
            mean = sum(self._calib) / n
            var = sum((r - mean) ** 2 for r in self._calib) / (n - 1)
            self.state.sigma_lph = max(math.sqrt(var), 0.05)
            self.state.calibrated = True

    def update(self, observed_lph, head) -> str:
        """Returns 'normal', 'leak', 'clog' or 'learning'."""
        exp = self.expected_lph(head)
        r = observed_lph - exp
        if not self.state.calibrated:
            self.calibrate(observed_lph, head)
            return "learning"
        rules = self.cfg.rules
        rel = abs(r) / exp if exp > 0 else 0
        big = abs(r) > rules.fault_sigma * self.state.sigma_lph and rel > rules.fault_min_rel_error
        self.state.streak_high = self.state.streak_high + 1 if (big and r > 0) else 0
        self.state.streak_low = self.state.streak_low + 1 if (big and r < 0) else 0
        if self.state.streak_high >= rules.fault_consecutive:
            return "leak"
        if self.state.streak_low >= rules.fault_consecutive:
            return "clog"
        return "normal"

# ---------------------------------------------------------------- Eq. (7)

def allocation_factor(storage_l: float, reserve_l: float, future_etc_mm: list, area_m2: float, efficiency: float) -> float:
    """alpha = min(1, usable storage / remaining seasonal demand)."""
    demand_l = sum(future_etc_mm) * area_m2 / efficiency
    if demand_l <= 0:
        return 1.0
    return max(0.0, min(1.0, (storage_l - reserve_l) / demand_l))


def days_of_supply(storage_l: float, reserve_l: float, daily_use_l: float) -> float:
    if daily_use_l <= 0:
        return float("inf")
    return max(0.0, (storage_l - reserve_l) / daily_use_l)

# ---------------------------------------------------------------- Eq. (8)

@dataclass
class SafetyResult:
    allowed: bool
    reasons: list


def safety_check(depletion: float, threshold: float, raining: bool, storage_l: float,
                 reserve_l: float, minutes: float, max_minutes: float) -> SafetyResult:
    """open <=> (Dr > p TAW) and not rain and (Vs > Vres) and (t <= tmax)."""
    reasons = []
    if not depletion > threshold:
        reasons.append("soil still moist enough")
    if raining:
        reasons.append("raining")
    if not storage_l > reserve_l:
        reasons.append("storage at reserve")
    if not minutes <= max_minutes:
        reasons.append(f"duration {minutes:.0f} min exceeds limit {max_minutes:.0f} min")
    return SafetyResult(allowed=not reasons, reasons=reasons)
