# -*- coding: utf-8 -*-

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from native_backend import (
    BACKEND_AUTO,
    ALGORITHM_AM,
    BACKEND_NATIVE,
    BACKEND_PYTHON_REFERENCE,
    DOT_CIRCLE,
    BackendConfig,
    NativeRipBackend,
    RipTileParams,
    STATUS_NOT_IMPLEMENTED,
    processing_plan_label,
    selected_backend_label,
)


class NativeBackendTests(unittest.TestCase):
    def test_environment_config_reads_backend_and_tile_sizes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RIP_BACKEND": "native",
                "RIP_TILE_SIZE": "1024",
                "RIP_STRIPE_HEIGHT": "256",
                "RIP_MEMORY_MAP": "0",
            },
            clear=False,
        ):
            config = BackendConfig.from_environment()

        self.assertEqual(config.mode, BACKEND_NATIVE)
        self.assertEqual(config.tile_size, 1024)
        self.assertEqual(config.stripe_height, 256)
        self.assertFalse(config.prefer_memory_map)

    def test_missing_native_library_falls_back_to_python_reference(self) -> None:
        backend = NativeRipBackend((Path(__file__).resolve().parent / ".test_tmp" / "missing_rip_core_native.dll"))
        self.assertFalse(backend.available)
        self.assertIn("not built", backend.info.reason or "")
        self.assertIn("Python reference", backend.info.label)
        self.assertIn("Python reference", selected_backend_label(BackendConfig(mode=BACKEND_PYTHON_REFERENCE)))

    def test_processing_plan_mentions_bounded_tiles_and_stripes(self) -> None:
        label = processing_plan_label(BackendConfig(tile_size=768, stripe_height=384, prefer_memory_map=False))
        self.assertIn("tiles=768px", label)
        self.assertIn("stripes=384px", label)
        self.assertIn("stream", label)

    def test_native_dll_screens_tile_when_built(self) -> None:
        backend = NativeRipBackend()
        if not backend.available:
            self.skipTest("native DLL is not built")
        params = RipTileParams(
            width=8,
            height=4,
            input_stride=8,
            output_stride=8,
            tile_x=0,
            tile_y=0,
            dpi=600.0,
            lpi=150.0,
            angle_deg=45.0,
            min_dot=0.02,
            algorithm=ALGORITHM_AM,
            dot_shape=DOT_CIRCLE,
            flags=0,
        )
        gray = bytes([255] * 8 + [128] * 16 + [0] * 8)
        output = backend.screen_tile(gray, params)
        self.assertEqual(len(output), 32)
        self.assertTrue(all(value == 0 for value in output[:8]))
        self.assertTrue(all(value == 255 for value in output[-8:]))
        self.assertIn(255, output[8:24])
    def test_tile_params_ctypes_layout_contains_production_geometry(self) -> None:
        fields = [name for name, _type in RipTileParams._fields_]
        self.assertEqual(
            fields,
            [
                "width",
                "height",
                "input_stride",
                "output_stride",
                "tile_x",
                "tile_y",
                "dpi",
                "lpi",
                "angle_deg",
                "min_dot",
                "algorithm",
                "dot_shape",
                "flags",
            ],
        )
        self.assertGreaterEqual(ctypes.sizeof(RipTileParams), 64)
        self.assertEqual(STATUS_NOT_IMPLEMENTED, 3)


if __name__ == "__main__":
    unittest.main()