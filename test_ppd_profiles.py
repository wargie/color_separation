# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import unittest

from ppd_profiles import discover_ppd_profiles, parse_ppd


class PpdProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = parse_ppd(Path("BCCDI1_SPARKXT2.PPD"))

    def test_esko_flexrip_profile_metadata(self) -> None:
        self.assertEqual(self.profile.name, "ESKO-CDI-SPARKXT2")
        self.assertEqual(self.profile.product, "FlexRip")
        self.assertEqual(self.profile.resolutions, (2000, 2100, 2400, 2540, 2800, 4000))
        self.assertEqual(len(self.profile.presets), 186)

    def test_flexo_screen_set_is_parsed(self) -> None:
        screens = self.profile.screen_specs(2400, 150)
        self.assertEqual(screens["C"].angle_deg, 7.5)
        self.assertEqual(screens["M"].angle_deg, 37.5)
        self.assertEqual(screens["Y"].angle_deg, 82.5)
        self.assertEqual(screens["K"].angle_deg, 67.5)
        self.assertEqual(screens["C"].frequency_lpi, 150.0)

    def test_supported_dot_shapes_are_exposed(self) -> None:
        engine_shapes = {item[2] for item in self.profile.dot_shapes}
        self.assertEqual(engine_shapes, {"circle", "ellipse", "square", "line"})

    def test_project_profile_discovery(self) -> None:
        profiles = discover_ppd_profiles(Path.cwd())
        self.assertIn("ESKO-CDI-SPARKXT2", {profile.name for profile in profiles})


if __name__ == "__main__":
    unittest.main()
