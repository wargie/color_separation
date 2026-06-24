# -*- coding: utf-8 -*-

from __future__ import annotations

from io import BytesIO
import logging
from pathlib import Path

import numpy as np
from PIL import Image


logger = logging.getLogger(__name__)
BITONAL_DIR_NAME = "Bitonal"


def is_prescreened_plate(
    image: Image.Image,
    *,
    sample_size: int = 512,
    midtone_limit: float = 0.01,
    max_limited_tone_levels: int = 8,
) -> bool:
    image.load()
    sample = image.convert("L")
    sample.load()
    sample.thumbnail((sample_size, sample_size), Image.Resampling.NEAREST)
    arr = np.asarray(sample, dtype=np.uint8)
    if arr.size == 0:
        return False
    unique_levels = np.unique(arr)
    midtone_ratio = float(np.mean((arr > 3) & (arr < 252)))
    if midtone_ratio <= midtone_limit:
        return True
    return len(unique_levels) <= max_limited_tone_levels


def is_bitonal_plate(image: Image.Image, *, sample_size: int = 512, midtone_limit: float = 0.0005) -> bool:
    image.load()
    sample = image.convert("L")
    sample.load()
    sample.thumbnail((sample_size, sample_size), Image.Resampling.NEAREST)
    arr = np.asarray(sample, dtype=np.uint8)
    if arr.size == 0:
        return False
    return float(np.mean((arr > 3) & (arr < 252))) <= midtone_limit


def save_bitonal_plate(source_path: Path, label: str, threshold: int = 252) -> Path | None:
    source_bytes = source_path.read_bytes()
    with Image.open(BytesIO(source_bytes)) as image:
        image.load()
        should_save = is_bitonal_plate(image)
        if should_save:
            gray = image.convert("L")
            gray.load()
            arr = np.asarray(gray, dtype=np.uint8)
            dots = arr < threshold
            bitonal = Image.fromarray(np.where(dots, 0, 255).astype(np.uint8)).convert("1")
        else:
            bitonal = None

    if bitonal is None:
        logger.info("Plate is not bitonal; keeping grayscale TIFF: %s", source_path)
        return None

    output_dir = source_path.parent / BITONAL_DIR_NAME
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{safe_bitonal_name(label)}.tif"
    bitonal.save(output_path, compression="group4")
    logger.info("Saved bitonal plate mask: %s -> %s", source_path, output_path)
    return output_path


def safe_bitonal_name(value: str) -> str:
    keep = []
    for char in value.strip():
        if char.isalnum() or char in {" ", "-", "_", "."}:
            keep.append(char)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip(" ._")
    return cleaned or "plate"
