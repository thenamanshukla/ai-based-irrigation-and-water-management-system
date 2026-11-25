"""All tunable settings in one place. Edit settings.json to override any value."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path


@dataclass
class Site:
    latitude_deg: float = 24.8          # Imphal; change for your site


@dataclass
class Crop:
    name: str = "tomato"
    # FAO-56 style stage lengths (days) and crop coefficients
    stage_days: tuple = (25, 35, 40, 20)            # initial, development, mid, late
    kc_ini: float = 0.70
    kc_mid: float = 1.05
    kc_end: float = 0.90
    root_depth_m: float = 0.40
    depletion_fraction_p: float = 0.40              # allowable depletion before irrigating


@dataclass
class Soil:
    theta_fc: float = 0.30      # field capacity (m3/m3), loam
    theta_wp: float = 0.15      # wilting point (m3/m3)


@dataclass
class Tank:
    capacity_l: float = 20.0
    depth_m: float = 0.30
    floor_above_emitters_m: float = 1.0     # z0
    sensor_to_floor_m: float = 0.30         # IR sensor mounted at the rim
    reserve_l: float = 2.0                  # never drain below this


@dataclass
class Emitters:
    count: int = 8
    k_lph: float = 0.63          # q = k * H^x, litres per hour, H in metres
    x: float = 0.5
    efficiency: float = 0.90     # drip application efficiency (eta)


@dataclass
class Zone:
    area_m2: float = 0.72        # 8 plants at about 0.09 m2 each


@dataclass
class Pond:
    capacity_l: float = 150.0    # storage that refills the header tank
    catchment_m2: float = 2.0    # roof or field area draining into the pond
    runoff_coeff: float = 0.8


@dataclass
class Rules:
    max_valve_min: float = 90.0
    stress_prob_threshold: float = 0.80
    fault_sigma: float = 3.0
    fault_min_rel_error: float = 0.25
    fault_consecutive: int = 3
    hub_timeout_min: float = 30.0
    season_days: int = 120
    max_reading_age_min: float = 30.0      # no plan if the latest reading is older than this
    min_readings_per_day: int = 72         # need at least 6 h of data to estimate ET0
    moisture_start_pct: float = 35.0       # real time rule: water when the 7 in 1 probe reads below this
    moisture_stop_pct: float = 40.0        # and stop at this level
    auto_minutes: float = 45.0             # one run (about 1000 ml on the prototype rig)
    auto_cooldown_min: float = 60.0        # no new automatic run within this time of the last command
    object_alert_gap_min: float = 10.0     # IR detections closer than this give one alert


@dataclass
class Service:
    planting_date: str = ""                # YYYY-MM-DD, required before the service starts
    plan_time: str = "06:00"               # local time of the daily decision
    db_path: str = "data/irrigation.sqlite"
    status_path: str = "data/status.json"
    log_path: str = "data/hub.log"
    serial_port: str = "/dev/ttyACM0"      # Arduino B gateway
    baud: int = 115200
    api_port: int = 8080                   # phone app connects to http://<pi address>:8080
    app_pin: str = ""                      # if set, the app must send this PIN to water or change settings
    farm_name: str = "My farm"
    llm_dir: str = "/home/pi/llama"        # llama_main, its libraries, model.pte and tokenizer.model
    llm_threads: int = 4                   # Cortex-A76 cores used for Llama
    llm_max_new_tokens: int = 160


@dataclass
class Config:
    service: Service = field(default_factory=Service)
    site: Site = field(default_factory=Site)
    crop: Crop = field(default_factory=Crop)
    soil: Soil = field(default_factory=Soil)
    tank: Tank = field(default_factory=Tank)
    emitters: Emitters = field(default_factory=Emitters)
    zone: Zone = field(default_factory=Zone)
    pond: Pond = field(default_factory=Pond)
    rules: Rules = field(default_factory=Rules)

    @property
    def tank_area_m2(self) -> float:
        return (self.tank.capacity_l / 1000.0) / self.tank.depth_m

    def to_dict(self):
        return asdict(self)


def load(path: str | None = None) -> Config:
    """Load defaults, then apply any overrides found in a JSON file."""
    cfg = Config()
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text())
        for section, values in data.items():
            if section.startswith("_"):
                continue                                   # allow "_comment" keys
            if not hasattr(cfg, section):
                raise ValueError(f"settings: unknown section '{section}'")
            obj = getattr(cfg, section)
            for k, v in values.items():
                if k.startswith("_"):
                    continue
                if not hasattr(obj, k):
                    raise ValueError(f"settings: unknown key '{section}.{k}'")
                setattr(obj, k, tuple(v) if isinstance(getattr(obj, k), tuple) else v)
    return cfg
