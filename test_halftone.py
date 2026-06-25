# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from halftone import apply_halftone, halftone_cell_size, round_dot_diameter_microns, screen_pitch_microns, screen_pitch_microns_per_cm


class HalftoneTests(unittest.TestCase):
    def test_cpu_preserves_paper_and_solids(self) -> None:
        source = np.full((300, 300), 128, dtype=np.uint8)
        source[:100] = 254
        source[200:] = 0
        image = Image.fromarray(source)

        for mode in ("am", "fm", "hybrid"):
            output = np.asarray(
                apply_halftone(
                    image,
                    mode=mode,
                    dpi=600,
                    frequency_lpi=150,
                    angle_deg=45,
                    prefer_gpu=False,
                )
            )
            self.assertTrue(np.all(output[:100] == 255))
            self.assertTrue(np.all(output[200:] == 0))

    def test_gpu_preserves_paper_and_solids(self) -> None:
        from gpu_halftone import get_opencl_backend

        if get_opencl_backend() is None:
            self.skipTest("OpenCL GPU is unavailable")

        source = np.full((300, 300), 128, dtype=np.uint8)
        source[:100] = 254
        source[200:] = 0
        image = Image.fromarray(source)

        for mode in ("am", "fm", "hybrid"):
            output = np.asarray(
                apply_halftone(
                    image,
                    mode=mode,
                    dpi=600,
                    frequency_lpi=150,
                    angle_deg=45,
                )
            )
            self.assertTrue(np.all(output[:100] == 255))
            self.assertTrue(np.all(output[200:] == 0))

    def test_cpu_spot_shapes_preserve_paper_and_solids(self) -> None:
        source = np.full((256, 256), 128, dtype=np.uint8)
        source[:32] = 254
        source[-32:] = 0
        image = Image.fromarray(source)

        outputs = []
        for shape in ("circle", "ellipse", "square", "line"):
            output = np.asarray(
                apply_halftone(
                    image,
                    mode="am",
                    dpi=2400,
                    frequency_lpi=150,
                    angle_deg=37.5,
                    spot_shape=shape,
                    prefer_gpu=False,
                )
            )
            self.assertTrue(np.all(output[:32] == 255))
            self.assertTrue(np.all(output[-32:] == 0))
            outputs.append(output)
        self.assertTrue(any(not np.array_equal(outputs[0], output) for output in outputs[1:]))

    def test_am_screening_is_limited_to_halftones(self) -> None:
        source = np.array(
            [[255, 254, 253, 252, 251, 128, 4, 3, 2, 1, 0]],
            dtype=np.uint8,
        )
        output = np.asarray(
            apply_halftone(
                Image.fromarray(source),
                mode="am",
                dpi=2400,
                frequency_lpi=150,
                angle_deg=45,
                prefer_gpu=False,
            )
        )
        self.assertTrue(np.all(output[:, :2] == 255))
        self.assertTrue(np.all(output[:, -2:] == 0))
        middle = output[:, 2:-2]
        self.assertTrue(np.any((middle > 0) & (middle < 255)) or np.any(middle != source[:, 2:-2]))

    def test_cell_size_matches_requested_lineature(self) -> None:
        self.assertAlmostEqual(halftone_cell_size(160.952, 150.0), 1.0730133333)
        self.assertEqual(halftone_cell_size(100.0, 150.0), 1.0)



    def test_physical_screen_geometry_matches_reference_table(self) -> None:
        self.assertAlmostEqual(screen_pitch_microns(150), 169.3333333, places=4)
        self.assertAlmostEqual(screen_pitch_microns_per_cm(60), 166.6666667, places=4)
        self.assertAlmostEqual(round_dot_diameter_microns(150, 0.01), 19.1, delta=0.1)
        self.assertAlmostEqual(round_dot_diameter_microns(150, 0.02), 27.0, delta=0.1)
        self.assertAlmostEqual(round_dot_diameter_microns(150, 0.03), 33.1, delta=0.1)
        self.assertAlmostEqual(round_dot_diameter_microns(150, 0.50), 135.1, delta=0.1)

    def test_highlight_tones_are_screened_not_dropped_as_paper(self) -> None:
        source = np.full((512, 512), 252, dtype=np.uint8)
        output = np.asarray(
            apply_halftone(
                Image.fromarray(source),
                mode="am",
                dpi=2400,
                frequency_lpi=150,
                angle_deg=45,
                prefer_gpu=False,
            )
        )
        self.assertGreater(np.count_nonzero(output == 0), 0)
        self.assertLess(np.count_nonzero(output == 0), output.size)

    def test_flexo_mode_holds_minimum_highlight_dot(self) -> None:
        source = np.full((256, 256), 251, dtype=np.uint8)
        output = np.asarray(
            apply_halftone(
                Image.fromarray(source),
                mode="flexo",
                dpi=2400,
                frequency_lpi=150,
                angle_deg=45,
                prefer_gpu=False,
            )
        )
        measured_ink = np.mean((255.0 - output.astype(np.float32)) / 255.0)
        self.assertGreater(float(measured_ink), 0.01)

    def test_error_diffusion_preserves_paper_and_solids(self) -> None:
        source = np.full((64, 64), 128, dtype=np.uint8)
        source[:8] = 254
        source[-8:] = 2
        output = np.asarray(
            apply_halftone(
                Image.fromarray(source),
                mode="error_diffusion",
                dpi=600,
                frequency_lpi=150,
                angle_deg=45,
                prefer_gpu=False,
            )
        )
        self.assertTrue(np.all(output[:8] == 255))
        self.assertTrue(np.all(output[-8:] == 0))

    def test_am_preserves_requested_coverage(self) -> None:
        image = Image.fromarray(np.full((800, 800), 128, dtype=np.uint8))
        output = np.asarray(
            apply_halftone(
                image,
                mode="am",
                dpi=600,
                frequency_lpi=150,
                angle_deg=45,
            )
        )
        measured_ink = np.mean((255.0 - output.astype(np.float32)) / 255.0)
        self.assertAlmostEqual(float(measured_ink), 0.5, delta=0.015)


if __name__ == "__main__":
    unittest.main()
