# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from halftone import SCREEN_MODE_NONE
from plate_bits import is_prescreened_plate
from rip_core import RenderLayer, backend_name, render_preview


class RipCoreTests(unittest.TestCase):
    def test_tiled_preview_scales_and_composites_layers(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
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


    def test_limited_tone_layer_can_be_screened(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            source = Path(tmp) / "limited.tif"
            arr = np.array([[255, 70, 128, 0]] * 32, dtype=np.uint8)
            Image.fromarray(arr).save(source)

            calls: list[str] = []

            def capture(image: Image.Image, **kwargs: object) -> Image.Image:
                calls.append(str(kwargs["mode"]))
                return image

            with patch.dict("os.environ", {"RIP_BACKEND": "python_reference"}, clear=False):
                with patch("rip_core.apply_halftone", side_effect=capture):
                    render_preview(
                        [RenderLayer(path=source, name="C", angle_deg=45, frequency_lpi=150)],
                        color_resolver=lambda _name: (0, 174, 239),
                        screen_mode="am",
                        max_size=64,
                        tile_size=64,
                    )

            self.assertEqual(calls, ["am"])

    def test_bitonal_layer_is_not_rescreened(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            source = Path(tmp) / "binary.tif"
            arr = np.array([[255, 0, 255, 0]] * 32, dtype=np.uint8)
            Image.fromarray(arr).save(source)

            with patch("rip_core.apply_halftone") as mocked:
                render_preview(
                    [RenderLayer(path=source, name="K", angle_deg=45, frequency_lpi=150)],
                    color_resolver=lambda _name: (30, 30, 30),
                    screen_mode="am",
                    max_size=64,
                    tile_size=64,
                )

            mocked.assert_not_called()

    def test_backend_name_is_stable_without_native_dll(self) -> None:
        label = backend_name().lower()
        self.assertTrue("renderer" in label or "native rip core" in label)


if __name__ == "__main__":
    unittest.main()
