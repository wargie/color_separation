# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image


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


@dataclass(frozen=True)
class ScreenSpec:
    frequency_lpi: float
    angle_deg: float


def default_screen_angle(plate_name: str) -> float:
    return DEFAULT_SCREEN_ANGLES.get(plate_name.upper(), 45.0)


def apply_am_halftone(image: Image.Image, dpi: int, frequency_lpi: float, angle_deg: float) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0

    if dpi <= 0 or frequency_lpi <= 0:
        return gray

    height, width = ink.shape
    cell_size = max(2.0, float(dpi) / float(frequency_lpi))
    yy, xx = np.indices((height, width), dtype=np.float32)

    theta = math.radians(angle_deg)
    cos_a = math.cos(theta)
    sin_a = math.sin(theta)
    rotated_x = xx * cos_a + yy * sin_a
    rotated_y = -xx * sin_a + yy * cos_a

    cell_x = ((rotated_x / cell_size) % 1.0) - 0.5
    cell_y = ((rotated_y / cell_size) % 1.0) - 0.5
    distance = np.sqrt(cell_x * cell_x + cell_y * cell_y) / math.sqrt(0.5)

    # A circular AM dot: ink coverage controls dot radius inside each screen cell.
    threshold = np.sqrt(np.clip(ink, 0.0, 1.0))
    dots = distance <= threshold
    screened = np.where(dots, 0, 255).astype(np.uint8)
    return Image.fromarray(screened, "L")


def apply_fm_halftone(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0
    noise = _deterministic_noise(ink.shape)
    screened = np.where(noise < ink, 0, 255).astype(np.uint8)
    return Image.fromarray(screened, "L")


def apply_hybrid_halftone(image: Image.Image, dpi: int, frequency_lpi: float, angle_deg: float) -> Image.Image:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    ink = (255.0 - arr) / 255.0
    am = np.asarray(apply_am_halftone(gray, dpi, frequency_lpi, angle_deg), dtype=np.uint8)
    fm = np.asarray(apply_fm_halftone(gray), dtype=np.uint8)
    use_fm = (ink < 0.20) | (ink > 0.85)
    screened = np.where(use_fm, fm, am).astype(np.uint8)
    return Image.fromarray(screened, "L")


def _deterministic_noise(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices((height, width), dtype=np.uint32)
    value = xx * np.uint32(374761393) + yy * np.uint32(668265263)
    value = (value ^ (value >> np.uint32(13))) * np.uint32(1274126177)
    value = value ^ (value >> np.uint32(16))
    return value.astype(np.float32) / np.float32(2**32 - 1)


def extract_postscript_screen_angles(source_path: Path) -> dict[str, ScreenSpec]:
    if source_path.suffix.lower() not in {".ps", ".eps"}:
        return {}

    try:
        text = source_path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return {}

    screens: dict[str, ScreenSpec] = {}
    screens.update(_extract_setcolorscreen(text))
    screens.update(_extract_halftone_blocks(text))
    return screens


def _extract_setcolorscreen(text: str) -> dict[str, ScreenSpec]:
    screens: dict[str, ScreenSpec] = {}
    for match in re.finditer(r"(?P<body>.{0,1200}?)\bsetcolorscreen\b", text, re.IGNORECASE | re.DOTALL):
        numbers = [float(value) for value in re.findall(r"[-+]?\d+(?:\.\d+)?", match.group("body"))]
        if len(numbers) < 8:
            continue
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
        r"/(?P<plate>Cyan|Magenta|Yellow|Black|C|M|Y|K)\b(?P<body>.{0,800}?)(?:sethalftone|setscreen)",
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
