# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from app import build_preview_image, effective_preview_dpi


class PreviewScaleTests(unittest.TestCase):
    def test_effective_dpi_tracks_thumbnail_scale(self) -> None:
        self.assertAlmostEqual(effective_preview_dpi(2000, 0.16), 320.0)

    def test_preview_halftone_uses_scaled_dpi(self) -> None:
        temp_root = Path(r"C:\tmp")
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
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
