# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image


logger = logging.getLogger(__name__)

DEFAULT_SCREEN_ANGLES = {
    "C": 15.0,
    "M": 75.0,
    "Y": 0.0,
    "K": 45.0,
}
DEFAULT_SCREEN_FREQUENCY = 150

SCREEN_MODE_NONE = "none"
SCREEN_MODE_AM = "am"
SCREEN_MODE_FM = "fm"
SCREEN_MODE_HYBRID = "hybrid"
SCREEN_MODE_FLEXO = "flexo"
SCREEN_MODE_ERROR_DIFFUSION = "error_diffusion"
SCREEN_MODE_CODES = {SCREEN_MODE_AM: 1, SCREEN_MODE_FM: 2, SCREEN_MODE_HYBRID: 3, SCREEN_MODE_FLEXO: 4}
SPOT_SHAPE_CODES = {"circle": 0, "ellipse": 1, "square": 2, "line": 3}
PAPER_VALUE_THRESHOLD = 252
SOLID_INK_VALUE_THRESHOLD = 3


@dataclass(frozen=True)
class ScreenSpec:
    frequency_lpi: float
    angle_deg: float


def halftone_cell_size(dpi: float, frequency_lpi: float) -> float:
    if dpi <= 0 or frequency_lpi <= 0:
        return 1.0
    return max(1.0, float(dpi) / float(frequency_lpi))


def default_screen_angle(plate_name: str) -> float:
    return DEFAULT_SCREEN_ANGLES.get(plate_name.upper(), 45.0)


def apply_am_halftone(
    image: Image.Image,
    dpi: float,
    frequency_lpi: float,
    angle_deg: float,
    spot_shape: str = "circle",
    minimum_dot: float = 0.0,
) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0

    if dpi <= 0 or frequency_lpi <= 0:
        return gray

    height, width = ink.shape
    cell_size = halftone_cell_size(dpi, frequency_lpi)
    yy, xx = np.indices((height, width), dtype=np.float32)

    theta = math.radians(angle_deg)
    cos_a = math.cos(theta)
    sin_a = math.sin(theta)
    rotated_x = xx * cos_a + yy * sin_a
    rotated_y = -xx * sin_a + yy * cos_a

    cell_x = ((rotated_x / cell_size) % 1.0) - 0.5
    cell_y = ((rotated_y / cell_size) % 1.0) - 0.5
    spot_threshold = _spot_threshold(cell_x, cell_y, spot_shape)
    ink = np.clip(ink, 0.0, 1.0)
    if minimum_dot > 0:
        ink = np.where((ink > 0.0) & (ink < minimum_dot), minimum_dot, ink)
    edge_width = np.float32(np.clip(0.75 / cell_size, 0.015, 0.12))
    dot_alpha = np.clip((ink - spot_threshold) / edge_width + 0.5, 0.0, 1.0)
    screened = np.rint(255.0 * (1.0 - dot_alpha)).astype(np.uint8)
    _preserve_paper_and_solids(screened, arr)
    return Image.fromarray(screened)


def apply_fm_halftone(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0
    noise = _deterministic_noise(ink.shape)
    screened = np.where(noise < ink, 0, 255).astype(np.uint8)
    _preserve_paper_and_solids(screened, arr)
    return Image.fromarray(screened)


def apply_hybrid_halftone(
    image: Image.Image,
    dpi: float,
    frequency_lpi: float,
    angle_deg: float,
    spot_shape: str = "circle",
) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0
    am = np.asarray(apply_am_halftone(gray, dpi, frequency_lpi, angle_deg, spot_shape), dtype=np.uint8)
    fm = np.asarray(apply_fm_halftone(gray), dtype=np.uint8)
    use_fm = (ink < 0.20) | (ink > 0.85)
    screened = np.where(use_fm, fm, am).astype(np.uint8)
    return Image.fromarray(screened)



def apply_error_diffusion_halftone(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    source = np.asarray(gray, dtype=np.float32)
    work = source.copy()
    height, width = work.shape
    output = np.empty((height, width), dtype=np.uint8)

    for y in range(height):
        left_to_right = y % 2 == 0
        x_range = range(width) if left_to_right else range(width - 1, -1, -1)
        for x in x_range:
            old = work[y, x]
            new = 0.0 if old < 128.0 else 255.0
            output[y, x] = np.uint8(new)
            error = old - new
            direction = 1 if left_to_right else -1
            nx = x + direction
            if 0 <= nx < width:
                work[y, nx] += error * 7.0 / 16.0
            if y + 1 < height:
                if 0 <= x - direction < width:
                    work[y + 1, x - direction] += error * 3.0 / 16.0
                work[y + 1, x] += error * 5.0 / 16.0
                if 0 <= nx < width:
                    work[y + 1, nx] += error * 1.0 / 16.0

    _preserve_paper_and_solids(output, source)
    return Image.fromarray(output)

def apply_halftone(
    image: Image.Image,
    *,
    mode: str,
    dpi: float,
    frequency_lpi: float,
    angle_deg: float,
    spot_shape: str = "circle",
    prefer_gpu: bool = True,
) -> Image.Image:
    gray = image.convert("L")
    if mode == SCREEN_MODE_NONE:
        return gray
    mode_code = SCREEN_MODE_CODES.get(mode)
    if mode == SCREEN_MODE_ERROR_DIFFUSION:
        return apply_error_diffusion_halftone(gray)
    if mode_code is None:
        raise ValueError(f"Unsupported halftone mode: {mode}")
    if prefer_gpu:
        try:
            from gpu_halftone import get_opencl_backend
            backend = get_opencl_backend()
            if backend is not None:
                source = np.asarray(gray, dtype=np.uint8)
                screened = backend.apply(
                    source,
                    mode=mode_code,
                    dpi=dpi,
                    frequency_lpi=frequency_lpi,
                    angle_deg=angle_deg,
                    spot_shape=SPOT_SHAPE_CODES.get(spot_shape, 0),
                )
                return Image.fromarray(screened)
        except Exception:
            logger.exception("GPU halftone failed, falling back to CPU")
    if mode == SCREEN_MODE_AM:
        return apply_am_halftone(gray, dpi, frequency_lpi, angle_deg, spot_shape)
    if mode == SCREEN_MODE_FLEXO:
        return apply_am_halftone(gray, dpi, frequency_lpi, angle_deg, spot_shape, minimum_dot=0.02)
    if mode == SCREEN_MODE_FM:
        return apply_fm_halftone(gray)
    return apply_hybrid_halftone(gray, dpi, frequency_lpi, angle_deg, spot_shape)


def _deterministic_noise(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices((height, width), dtype=np.uint32)
    value = xx * np.uint32(374761393) + yy * np.uint32(668265263)
    value = (value ^ (value >> np.uint32(13))) * np.uint32(1274126177)
    value = value ^ (value >> np.uint32(16))
    return value.astype(np.float32) / np.float32(2**32 - 1)


def _preserve_paper_and_solids(screened: np.ndarray, source: np.ndarray) -> None:
    screened[source >= PAPER_VALUE_THRESHOLD] = 255
    screened[source <= SOLID_INK_VALUE_THRESHOLD] = 0


def _circular_spot_threshold(distance: np.ndarray) -> np.ndarray:
    radius_sq = distance * distance
    threshold = np.empty(distance.shape, dtype=np.float32)
    inner = distance <= 0.5
    threshold[inner] = np.float32(math.pi) * radius_sq[inner]

    outer = ~inner
    outer_radius = distance[outer]
    outer_radius_sq = radius_sq[outer]
    segment = outer_radius_sq * np.arccos(0.5 / outer_radius)
    segment -= 0.5 * np.sqrt(np.maximum(outer_radius_sq - 0.25, 0.0))
    threshold[outer] = np.float32(math.pi) * outer_radius_sq - 4.0 * segment
    return np.clip(threshold, 0.0, 1.0)


def _spot_threshold(cell_x: np.ndarray, cell_y: np.ndarray, spot_shape: str) -> np.ndarray:
    if spot_shape == "square":
        return np.clip(4.0 * np.maximum(np.abs(cell_x), np.abs(cell_y)) ** 2, 0.0, 1.0)
    if spot_shape == "line":
        return np.clip(2.0 * np.abs(cell_y), 0.0, 1.0)
    if spot_shape == "ellipse":
        distance = np.sqrt((cell_x * 0.75) ** 2 + (cell_y / 0.75) ** 2)
        return _circular_spot_threshold(distance)
    return _circular_spot_threshold(np.sqrt(cell_x * cell_x + cell_y * cell_y))


def extract_postscript_screen_angles(source_path: Path) -> dict[str, ScreenSpec]:
    if source_path.suffix.lower() not in {".ps", ".eps"}:
        return {}

    screens: dict[str, ScreenSpec] = {}
    recent_lines: deque[str] = deque(maxlen=40)
    try:
        with source_path.open("r", encoding="latin-1", errors="replace") as handle:
            for line in handle:
                recent_lines.append(line)
                lower_line = line.lower()
                if "setcolorscreen" in lower_line:
                    screens.update(_extract_setcolorscreen("".join(recent_lines)))
                if "sethalftone" in lower_line or "setscreen" in lower_line:
                    screens.update(_extract_halftone_blocks("".join(recent_lines)))
    except OSError:
        return {}
    return screens


def _extract_setcolorscreen(text: str) -> dict[str, ScreenSpec]:
    screens: dict[str, ScreenSpec] = {}
    before_operator = re.split(r"\bsetcolorscreen\b", text, flags=re.IGNORECASE)[0]
    numbers = [float(value) for value in re.findall(r"[-+]?\d+(?:\.\d+)?", before_operator)]
    if len(numbers) < 8:
        return screens
    values = numbers[-8:]
    for plate, offset in zip(("C", "M", "Y", "K"), range(0, 8, 2)):
        frequency = values[offset]
        angle = values[offset + 1]
        if frequency > 0:
            screens[plate] = ScreenSpec(frequency_lpi=frequency, angle_deg=angle)
    return screens


def _extract_halftone_blocks(text: str) -> dict[str, ScreenSpec]:
    screens: dict[str, ScreenSpec] = {}
    block_pattern = re.compile(
        r"/(?P<plate>Cyan|Magenta|Yellow|Black|C|M|Y|K)\b(?P<body>.{0,4000}?)(?:sethalftone|setscreen)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in block_pattern.finditer(text):
        plate = _normalize_plate(match.group("plate"))
        body = match.group("body")
        frequency_match = re.search(r"/Frequency\s+([-+]?\d+(?:\.\d+)?)", body, re.IGNORECASE)
        angle_match = re.search(r"/Angle\s+([-+]?\d+(?:\.\d+)?)", body, re.IGNORECASE)
        if not frequency_match or not angle_match:
            continue
        screens[plate] = ScreenSpec(
            frequency_lpi=float(frequency_match.group(1)),
            angle_deg=float(angle_match.group(1)),
        )
    return screens


def _normalize_plate(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"cyan", "c"}:
        return "C"
    if normalized in {"magenta", "m"}:
        return "M"
    if normalized in {"yellow", "y"}:
        return "Y"
    if normalized in {"black", "k"}:
        return "K"
    return value.strip()
