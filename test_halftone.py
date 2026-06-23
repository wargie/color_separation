# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from halftone import apply_halftone


class HalftoneTests(unittest.TestCase):
    def test_cpu_preserves_paper_and_solids(self) -> None:
        source = np.full((300, 300), 128, dtype=np.uint8)
        source[:100] = 255
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
        source[:100] = 255
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
        self.assertAlmostEqual(float(np.mean(output == 0)), 0.5, delta=0.01)


if __name__ == "__main__":
    unittest.main()
