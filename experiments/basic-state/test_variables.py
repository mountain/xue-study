"""Physical meaning and retrieval guard checks, independent of live services."""
import unittest
import numpy as np

from variables import (BY_CODE, FIELDS, cds_monthly_requests, domain_mask,
                       radiation_to_flux, resolve)


class VariableChecks(unittest.TestCase):
    def test_original_quantities_and_vector_pairs_are_retained(self):
        original = {"t850", "t2m", "sst", "z1000", "z500", "r850", "r700",
                    "u850", "u250", "v850", "v250", "w500", "w700", "tisr", "str", "sd"}
        self.assertTrue(original.issubset(BY_CODE))
        self.assertEqual(len({f.code for f in FIELDS}), len(FIELDS))
        self.assertEqual(len({f.name for f in FIELDS}), len(FIELDS))
        for level in (250, 500, 850):
            self.assertEqual(BY_CODE[f"u{level}"].level_hpa, BY_CODE[f"v{level}"].level_hpa)
        self.assertEqual(resolve("2_metre_temperature").cds_variable, "2m_temperature")
        self.assertEqual(resolve("total_incoming_shortwave_radiation").role, "forcing")

    def test_same_flux_has_different_hourly_and_monthly_energy(self):
        hourly = np.array([360000., -360000.])
        daily = hourly * 24
        np.testing.assert_array_equal(
            radiation_to_flux(hourly, product="era5_hourly_reanalysis"), [100, -100])
        np.testing.assert_array_equal(
            radiation_to_flux(daily, product="era5_monthly_averaged_reanalysis"), [100, -100])
        with self.assertRaises(ValueError):
            radiation_to_flux(hourly, product="six_hour_cadence")

    def test_underground_and_land_ocean_domains(self):
        sp = np.array([58000., 84000., 86000., 101000., np.nan])
        np.testing.assert_array_equal(domain_mask(BY_CODE["t850"], surface_pressure=sp),
                                      [False, False, True, True, False])
        np.testing.assert_array_equal(domain_mask(BY_CODE["z1000"], surface_pressure=sp),
                                      [False, False, False, True, False])
        lsm = np.array([0, 0.4, 0.5, 1, np.nan])
        np.testing.assert_array_equal(domain_mask(BY_CODE["sst"], land_sea_mask=lsm),
                                      [True, True, False, False, False])
        np.testing.assert_array_equal(domain_mask(BY_CODE["sd"], land_sea_mask=lsm),
                                      [False, False, True, True, False])
        with self.assertRaises(ValueError):
            domain_mask(BY_CODE["w700"])

    def test_monthly_requests_cover_exactly_the_configured_fields(self):
        plan = cds_monthly_requests(2020, [2, 1, 2])
        seen = set()
        for item in plan:
            r = item["request"]
            self.assertEqual(r["product_type"], ["monthly_averaged_reanalysis"])
            self.assertEqual(r["month"], ["01", "02"])
            for name in r["variable"]:
                for level in r.get("pressure_level", [None]):
                    seen.add((name, int(level) if level else None))
        self.assertEqual(seen, {(f.cds_variable, f.level_hpa) for f in FIELDS})


if __name__ == "__main__":
    unittest.main()
