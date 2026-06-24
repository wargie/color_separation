# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from plate_bits import BITONAL_DIR_NAME, is_prescreened_plate, save_bitonal_plate


class PlateBitsTests(unittest.TestCase):
    def test_limited_tone_plate_is_saved_as_one_bit_tiff(self) -> None:
        temp_root = Path(r"C:\tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            source = Path(tmp) / "spot.tif"
            arr = np.array([[255, 255, 70, 0], [255, 128, 255, 0]], dtype=np.uint8)
            Image.fromarray(arr).save(source)

            output = save_bitonal_plate(source, "PANTONE 281 C")

            self.assertIsNotNone(output)
            assert output is not None
            self.assertEqual(output.parent.name, BITONAL_DIR_NAME)
            with Image.open(output) as image:
                self.assertEqual(image.mode, "1")
                self.assertEqual(image.size, (4, 2))
                pixels = np.asarray(image.convert("L"), dtype=np.uint8)
            self.assertEqual(int(pixels[0, 0]), 255)
            self.assertEqual(int(pixels[0, 2]), 0)
            self.assertEqual(int(pixels[1, 1]), 0)

    def test_gradient_plate_remains_contone(self) -> None:
        gradient = Image.fromarray(np.tile(np.arange(128, dtype=np.uint8), (128, 1)))
        self.assertFalse(is_prescreened_plate(gradient))


if __name__ == "__main__":
    unittest.main()
