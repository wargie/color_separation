# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import math
import os
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image

from halftone import DEFAULT_SCREEN_FREQUENCY, SCREEN_MODE_NONE, apply_halftone, default_screen_angle
from inkcalc import DEFAULT_DPI
from plate_bits import is_bitonal_plate


logger = logging.getLogger(__name__)
ColorResolver = Callable[[str], tuple[int, int, int]]


@dataclass(frozen=True)
class RenderLayer:
    path: Path
    name: str
    enabled: bool = True
    angle_deg: float | None = None
    frequency_lpi: float | None = None


@dataclass(frozen=True)
class TileRenderRequest:
    layers: tuple[RenderLayer, ...]
    max_size: int = 8192
    dpi: float = DEFAULT_DPI
    screen_mode: str = SCREEN_MODE_NONE
    fallback_frequency_lpi: float = DEFAULT_SCREEN_FREQUENCY
    spot_shape: str = "circle"
    tile_size: int = 512


class NativeRipCore:
    def __init__(self, dll_path: Path | None = None) -> None:
        root = Path(__file__).resolve().parent
        candidate = dll_path or Path(os.environ.get("RIP_CORE_NATIVE_DLL", root / "native" / "rip_core_native.dll"))
        self.dll_path = candidate
        self.available = False
        self._dll: ctypes.CDLL | None = None
        if candidate.exists():
            try:
                self._dll = ctypes.CDLL(str(candidate))
                self.available = True
            except OSError as exc:
                logger.warning("Native RIP core is unavailable: %s", exc)

    @property
    def name(self) -> str:
        return f"Native DLL: {self.dll_path}" if self.available else "Python tiled renderer"


_native_core: NativeRipCore | None = None


def backend_name() -> str:
    global _native_core
    if _native_core is None:
        _native_core = NativeRipCore()
    return _native_core.name


def layers_from_dicts(layers: Iterable[dict[str, object]]) -> list[RenderLayer]:
    result: list[RenderLayer] = []
    for layer in layers:
        result.append(
            RenderLayer(
                path=Path(layer["path"]),
                name=str(layer["name"]),
                enabled=bool(layer.get("enabled", True)),
                angle_deg=_optional_float(layer.get("angle_deg")),
                frequency_lpi=_optional_float(layer.get("frequency_lpi")),
            )
        )
    return result


def render_preview(
    layers: Iterable[RenderLayer],
    *,
    color_resolver: ColorResolver,
    max_size: int = 8192,
    dpi: float = DEFAULT_DPI,
    screen_mode: str = SCREEN_MODE_NONE,
    fallback_frequency_lpi: float = DEFAULT_SCREEN_FREQUENCY,
    spot_shape: str = "circle",
    tile_size: int = 512,
) -> Image.Image:
    request = TileRenderRequest(
        layers=tuple(layer for layer in layers if layer.enabled),
        max_size=max_size,
        dpi=dpi,
        screen_mode=screen_mode,
        fallback_frequency_lpi=fallback_frequency_lpi,
        spot_shape=spot_shape,
        tile_size=tile_size,
    )
    if not request.layers:
        return Image.new("RGB", (600, 400), "white")
    return _render_preview_python(request, color_resolver)


def _render_preview_python(request: TileRenderRequest, color_resolver: ColorResolver) -> Image.Image:
    opened: list[tuple[RenderLayer, Image.Image, tuple[int, int], bool]] = []
    try:
        for layer in request.layers:
            image = Image.open(layer.path)
            opened.append((layer, image, image.size, is_bitonal_plate(image)))

        base_width, base_height = opened[0][2]
        scale = min(1.0, request.max_size / base_width, request.max_size / base_height)
        output_size = (max(1, int(round(base_width * scale))), max(1, int(round(base_height * scale))))
        output = Image.new("RGB", output_size, "white")

        for top in range(0, output_size[1], request.tile_size):
            for left in range(0, output_size[0], request.tile_size):
                right = min(output_size[0], left + request.tile_size)
                bottom = min(output_size[1], top + request.tile_size)
                tile = _render_tile_python(
                    opened,
                    output_box=(left, top, right, bottom),
                    base_size=(base_width, base_height),
                    output_scale=scale,
                    dpi=request.dpi,
                    screen_mode=request.screen_mode,
                    fallback_frequency_lpi=request.fallback_frequency_lpi,
                    spot_shape=request.spot_shape,
                    color_resolver=color_resolver,
                )
                output.paste(tile, (left, top))
        return output
    finally:
        for _layer, image, _size, _prescreened in opened:
            image.close()


def _render_tile_python(
    opened_layers: list[tuple[RenderLayer, Image.Image, tuple[int, int], bool]],
    *,
    output_box: tuple[int, int, int, int],
    base_size: tuple[int, int],
    output_scale: float,
    dpi: float,
    screen_mode: str,
    fallback_frequency_lpi: float,
    spot_shape: str,
    color_resolver: ColorResolver,
) -> Image.Image:
    left, top, right, bottom = output_box
    tile_width = right - left
    tile_height = bottom - top
    composite = np.full((tile_height, tile_width, 3), 255.0, dtype=np.float32)

    base_source_box = (
        left / output_scale,
        top / output_scale,
        right / output_scale,
        bottom / output_scale,
    )
    base_width, base_height = base_size

    for layer, image, source_size, bitonal in opened_layers:
        source_box = _map_source_box(base_source_box, base_size, source_size)
        gray = image.convert("L").crop(source_box)
        if gray.size != (tile_width, tile_height):
            gray = gray.resize((tile_width, tile_height), Image.Resampling.LANCZOS)

        if screen_mode != SCREEN_MODE_NONE and not bitonal:
            frequency = layer.frequency_lpi or fallback_frequency_lpi
            angle = layer.angle_deg if layer.angle_deg is not None else default_screen_angle(layer.name)
            gray = apply_halftone(
                gray,
                mode=screen_mode,
                dpi=max(1.0, dpi * output_scale),
                frequency_lpi=float(frequency),
                angle_deg=float(angle),
                spot_shape=spot_shape,
            )

        ink = (255.0 - np.asarray(gray, dtype=np.float32)) / 255.0
        color = np.asarray(color_resolver(layer.name), dtype=np.float32) / 255.0
        transmittance = 1.0 - ink[..., None] * (1.0 - color)
        composite *= transmittance

    return Image.fromarray(np.clip(composite, 0, 255).astype(np.uint8))


def _map_source_box(
    base_source_box: tuple[float, float, float, float],
    base_size: tuple[int, int],
    source_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    base_width, base_height = base_size
    source_width, source_height = source_size
    scale_x = source_width / base_width
    scale_y = source_height / base_height
    left = math.floor(base_source_box[0] * scale_x)
    top = math.floor(base_source_box[1] * scale_y)
    right = math.ceil(base_source_box[2] * scale_x)
    bottom = math.ceil(base_source_box[3] * scale_y)
    return (
        _clamp(left, 0, source_width),
        _clamp(top, 0, source_height),
        _clamp(right, 0, source_width),
        _clamp(bottom, 0, source_height),
    )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
