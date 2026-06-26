# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from app import build_preview_image, effective_preview_dpi, preview_ink_rgb


class PreviewScaleTests(unittest.TestCase):
    def test_effective_dpi_tracks_thumbnail_scale(self) -> None:
        self.assertAlmostEqual(effective_preview_dpi(2000, 0.16), 320.0)

    def test_preview_halftone_uses_scaled_dpi(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tif", dir=temp_root, delete=False) as handle:
            path = Path(handle.name)
        try:
            gradient = np.tile(np.linspace(0, 255, 1000, dtype=np.uint8), (500, 1))
            Image.fromarray(gradient).save(path, dpi=(1000, 1000))
            captured: list[float] = []

            def capture(image: Image.Image, **kwargs: object) -> Image.Image:
                captured.append(float(kwargs["dpi"]))
                return image

            with patch.dict("os.environ", {"RIP_BACKEND": "python_reference"}, clear=False):
                with patch("rip_core.apply_halftone", side_effect=capture):
                    build_preview_image(
                        [{"name": "K", "path": path, "enabled": True, "angle_deg": 45.0}],
                        max_size=200,
                        dpi=1000,
                        screen_mode="am",
                        fallback_frequency_lpi=100,
                    )
            self.assertEqual(len(captured), 1)
            self.assertAlmostEqual(captured[0], 200.0)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def test_known_pantone_preview_colors_are_realistic(self) -> None:
        green = preview_ink_rgb("PANTONE 349 C")
        brown = preview_ink_rgb("PANTONE 7587 C")
        self.assertGreater(green[1], green[0])
        self.assertGreater(green[1], green[2])
        self.assertGreater(brown[0], brown[2])
        self.assertGreater(brown[1], brown[2])

    def test_unknown_pantone_uses_number_family_not_hash_color(self) -> None:
        color = preview_ink_rgb("PANTONE 354 C")
        self.assertGreater(color[1], color[0])
        self.assertGreater(color[1], color[2])


if __name__ == "__main__":
    unittest.main()
