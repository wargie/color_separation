# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from halftone import SCREEN_MODE_NONE
from rip_core import RenderLayer, backend_name, is_prescreened_plate, render_preview


class RipCoreTests(unittest.TestCase):
    def test_tiled_preview_scales_and_composites_layers(self) -> None:
        temp_root = Path(r"C:\tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp)
            cyan = root / "c.tif"
            yellow = root / "y.tif"
            Image.new("L", (800, 400), 128).save(cyan)
            Image.new("L", (800, 400), 255).save(yellow)

            preview = render_preview(
                [
                    RenderLayer(path=cyan, name="C"),
                    RenderLayer(path=yellow, name="Y"),
                ],
                color_resolver=lambda name: {"C": (0, 174, 239), "Y": (255, 221, 0)}[name],
                max_size=200,
                screen_mode=SCREEN_MODE_NONE,
                tile_size=64,
            )

            self.assertEqual(preview.size, (200, 100))
            sample = np.asarray(preview, dtype=np.uint8)[50, 100]
            self.assertLess(int(sample[0]), 140)
            self.assertGreater(int(sample[2]), 240)

    def test_prescreened_plate_detection(self) -> None:
        binary = Image.fromarray(np.where(np.indices((120, 120))[0] % 2 == 0, 0, 255).astype(np.uint8))
        limited_tone = Image.fromarray(np.resize(np.array([0, 70, 128, 255], dtype=np.uint8), (120, 120)))
        gradient = Image.fromarray(np.tile(np.arange(120, dtype=np.uint8), (120, 1)))
        self.assertTrue(is_prescreened_plate(binary))
        self.assertTrue(is_prescreened_plate(limited_tone))
        self.assertFalse(is_prescreened_plate(gradient))

    def test_backend_name_is_stable_without_native_dll(self) -> None:
        self.assertIn("renderer", backend_name().lower())


if __name__ == "__main__":
    unittest.main()
