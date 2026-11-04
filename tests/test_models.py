"""Unit tests for the core equations. Run:  python -m unittest discover tests"""
import unittest
from irrigation import config, models as M
from irrigation.planner import plan, DailyInputs


class TestEquations(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config()

    def test_ra_fao56_example(self):
        # FAO-56 Example 8: 20 deg S, 3 September -> Ra = 32.2 MJ m-2 day-1
        ra_mj = M.extraterrestrial_radiation_mm(-20, 246) / 0.408
        self.assertAlmostEqual(ra_mj, 32.2, delta=0.2)

    def test_et0_reasonable(self):
        et0 = M.et0_hargreaves(32, 22, 24.8, 120)
        self.assertTrue(3.5 < et0 < 7.5, et0)
        self.assertEqual(M.et0_hargreaves(25, 25, 24.8, 120), 0.0)   # no range, no ET

    def test_kc_curve(self):
        c = self.cfg.crop
        self.assertEqual(M.crop_coefficient(c, 1), c.kc_ini)
        self.assertEqual(M.crop_coefficient(c, 70), c.kc_mid)
        self.assertAlmostEqual(M.crop_coefficient(c, 500), c.kc_end)

    def test_depletion_and_taw(self):
        s, c = self.cfg.soil, self.cfg.crop
        self.assertAlmostEqual(M.taw_mm(s, c), 60.0)
        self.assertAlmostEqual(M.depletion_mm(s.theta_fc, s, c), 0.0)
        self.assertAlmostEqual(M.depletion_mm(0.25, s, c), 20.0)

    def test_lower_head_needs_longer_time(self):
        em = self.cfg.emitters
        t_full = M.irrigation_minutes(5, 0.72, 1.30, em)
        t_low = M.irrigation_minutes(5, 0.72, 1.05, em)
        self.assertGreater(t_low, t_full)
        # same volume delivered either way: flow x time is constant
        q = lambda h: em.efficiency * em.count * M.emitter_flow_lph(h, em)
        self.assertAlmostEqual(q(1.30) * t_full, q(1.05) * t_low, places=6)

    def test_allocation_factor(self):
        self.assertEqual(M.allocation_factor(1000, 2, [4] * 30, 0.72, 0.9), 1.0)
        a = M.allocation_factor(50, 2, [4] * 30, 0.72, 0.9)
        self.assertAlmostEqual(a, 48 / (120 * 0.72 / 0.9), places=6)

    def test_safety_rule(self):
        ok = M.safety_check(30, 24, False, 15, 2, 60, 90)
        self.assertTrue(ok.allowed)
        for args, reason in [((30, 24, True, 15, 2, 60, 90), "raining"),
                             ((10, 24, False, 15, 2, 60, 90), "soil"),
                             ((30, 24, False, 2, 2, 60, 90), "reserve"),
                             ((30, 24, False, 15, 2, 120, 90), "exceeds")]:
            r = M.safety_check(*args)
            self.assertFalse(r.allowed)
            self.assertTrue(any(reason in x for x in r.reasons))

    def test_fault_detector(self):
        d = M.FaultDetector(self.cfg)
        head = 1.2
        exp = d.expected_lph(head)
        for i in range(10):
            d.update(exp + (0.1 if i % 2 else -0.1), head)          # commissioning
        self.assertTrue(d.state.calibrated)
        self.assertEqual([d.update(exp * 0.5, head) for _ in range(3)][-1], "clog")
        d2 = M.FaultDetector(self.cfg)
        for i in range(10):
            d2.update(exp + (0.1 if i % 2 else -0.1), head)
        self.assertEqual([d2.update(exp * 1.5, head) for _ in range(3)][-1], "leak")
        self.assertEqual(d2.update(exp, head), "normal")


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config()

    def x(self, **kw):
        base = dict(day_of_year=120, day_after_planting=40, t_max=32, t_min=22, theta=0.30,
                    raining=False, tank_depth_m=0.25, pond_l=100, stress_prob=0.1)
        base.update(kw)
        return DailyInputs(**base)

    def test_wet_soil_waits(self):
        self.assertEqual(plan(self.cfg, self.x(theta=0.30)).action, "wait")

    def test_dry_soil_waters_within_limit(self):
        d = plan(self.cfg, self.x(theta=0.20))
        self.assertEqual(d.action, "water")
        self.assertLessEqual(d.minutes, self.cfg.rules.max_valve_min)

    def test_rain_blocks(self):
        d = plan(self.cfg, self.x(theta=0.20, raining=True))
        self.assertEqual(d.action, "blocked")
        self.assertIn("raining", d.reasons)

    def test_stress_brings_watering_forward(self):
        theta = 0.30 - 0.04    # depletion 16 mm: below the 24 mm threshold, above half of it
        cool = dict(t_max=24, t_min=20)   # low demand, so the 24 h forecast stays below threshold
        self.assertEqual(plan(self.cfg, self.x(theta=theta, stress_prob=0.1, **cool)).action, "wait")
        d = plan(self.cfg, self.x(theta=theta, stress_prob=0.95, **cool))
        self.assertEqual(d.action, "water")
        self.assertTrue(any("camera" in r for r in d.reasons))

    def test_low_storage_scales_down(self):
        d = plan(self.cfg, self.x(theta=0.20, tank_depth_m=0.10, pond_l=5))
        self.assertLess(d.alpha, 1.0)


if __name__ == "__main__":
    unittest.main()
