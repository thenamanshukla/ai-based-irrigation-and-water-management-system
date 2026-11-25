"""Daily irrigation decision: combines Eqs. (1) to (8) into one plan."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from . import models as M


@dataclass
class DailyInputs:
    day_of_year: int
    day_after_planting: int
    t_max: float                 # yesterday's air max, deg C
    t_min: float                 # yesterday's air min, deg C
    theta: float                 # current soil moisture, m3/m3
    raining: bool
    tank_depth_m: float
    pond_l: float
    stress_prob: float | None = None   # from the IMX500 camera, 0..1; None if no camera
    recent_et0: list = field(default_factory=list)   # last few days ET0 for planning


@dataclass
class Decision:
    action: str                  # "water", "wait" or "blocked"
    minutes: float
    net_depth_mm: float
    litres: float
    et0_mm: float
    etc_mm: float
    kc: float
    depletion_mm: float
    threshold_mm: float
    theta_24h: float
    alpha: float
    storage_l: float
    days_left: float
    head_m: float
    stress_prob: float
    reasons: list

    def to_dict(self):
        return asdict(self)


def plan(cfg, x: DailyInputs, planning_horizon_days: int = 30) -> Decision:
    crop, soil, tank, em, zone = cfg.crop, cfg.soil, cfg.tank, cfg.emitters, cfg.zone

    # Eq. (1), (2): yesterday's crop water use
    et0 = M.et0_hargreaves(x.t_max, x.t_min, cfg.site.latitude_deg, x.day_of_year)
    kc = M.crop_coefficient(crop, x.day_after_planting)
    etc = M.etc(et0, kc)

    # Eq. (3): depletion and trigger
    taw = M.taw_mm(soil, crop)
    dr = M.depletion_mm(x.theta, soil, crop)
    threshold = crop.depletion_fraction_p * taw
    theta_24 = M.forecast_theta(x.theta, etc, crop, 24, soil=soil)
    dr_24 = M.depletion_mm(theta_24, soil, crop)

    # Eq. (4): storage and head
    tank_l = M.tank_volume_l(x.tank_depth_m, cfg.tank_area_m2)
    storage = tank_l + x.pond_l
    head = M.head_m(x.tank_depth_m, tank)

    # Eq. (7): seasonal allocation over the planning horizon
    et0_ref = sum(x.recent_et0) / len(x.recent_et0) if x.recent_et0 else et0
    remaining = max(0, cfg.rules.season_days - x.day_after_planting)
    horizon = min(planning_horizon_days, remaining) or 1
    future = [M.etc(et0_ref, M.crop_coefficient(crop, x.day_after_planting + d)) for d in range(1, horizon + 1)]
    alpha = M.allocation_factor(storage, tank.reserve_l, future, zone.area_m2, em.efficiency)
    daily_use = etc * zone.area_m2 / em.efficiency
    days_left = M.days_of_supply(storage, tank.reserve_l, daily_use)

    reasons = []
    # Trigger: depletion now, or by tomorrow, or plant looks stressed
    stressed = x.stress_prob is not None and x.stress_prob >= cfg.rules.stress_prob_threshold
    effective_threshold = threshold
    due = dr > threshold
    if not due and dr_24 > threshold:
        due = True
        effective_threshold = min(threshold, dr - 1e-6)
        reasons.append("soil will cross the threshold within 24 h")
    if not due and stressed and dr > 0.5 * threshold:
        due = True
        effective_threshold = 0.5 * threshold
        reasons.append(f"camera reports stress ({x.stress_prob:.0%})")

    net_depth = dr * alpha if due else 0.0
    minutes = M.irrigation_minutes(net_depth, zone.area_m2, head, em) if due else 0.0
    if minutes > cfg.rules.max_valve_min:
        # Low head drippers are slow: apply what fits in the time limit, carry the rest to tomorrow
        net_depth *= cfg.rules.max_valve_min / minutes
        minutes = cfg.rules.max_valve_min
        reasons.append("capped at the maximum valve time; remaining need carried to the next day")
    litres = net_depth * zone.area_m2 / em.efficiency

    if not due:
        reasons.append("soil still moist enough")
        action = "wait"
    else:
        # Eq. (8): safety rule
        s = M.safety_check(dr, effective_threshold, x.raining, storage, tank.reserve_l,
                           minutes, cfg.rules.max_valve_min)
        if s.allowed:
            action = "water"
            if alpha < 1:
                reasons.append(f"storage short: applying {alpha:.0%} of full need")
        else:
            action = "blocked"
            reasons += s.reasons

    return Decision(action, round(minutes, 1), round(net_depth, 2), round(litres, 2), round(et0, 2),
                    round(etc, 2), round(kc, 3), round(dr, 1), round(threshold, 1), round(theta_24, 3),
                    round(alpha, 2), round(storage, 1), round(days_left, 1), round(head, 3),
                    None if x.stress_prob is None else round(x.stress_prob, 2), reasons)
