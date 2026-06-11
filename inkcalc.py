# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import shutil
import subprocess
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image


DEFAULT_DPI = 600
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "Separation"
PAREN_NAME_PAT = re.compile(r"\((.+?)\)\.tif$", re.IGNORECASE)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateCoverage:
    name: str
    percent: float
    kind: str


@dataclass(frozen=True)
class CoverageResult:
    pdf_path: Path
    output_dir: Path
    plates: list[PlateCoverage]


ProgressCallback = Callable[[str], None]


def find_ghostscript() -> str:
    for name in ("gswin64c", "gswin64c.exe", "gswin32c", "gswin32c.exe", "gs"):
        path = shutil.which(name)
        if path:
            logger.info("Ghostscript found: %s", path)
            return path
    logger.error("Ghostscript executable was not found in PATH")
    raise RuntimeError("Ghostscript не найден. Установите Ghostscript и добавьте gswin64c в PATH.")


def first_pdf_near_script() -> Path | None:
    pdfs = sorted(Path(__file__).resolve().parent.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def make_output_dir(output_root: Path) -> Path:
    output_dir = output_root / f"temp_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory created: %s", output_dir)
    return output_dir


def run_tiffsep(gs_path: str, pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "sep_%03d.tif"
    cmd = [
        gs_path,
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=tiffsep",
        f"-r{dpi}",
        "-dSimulateOverprint=true",
        "-dOverprint=true",
        "-dOPM=1",
        f"-sOutputFile={output_file}",
        str(pdf_path),
    ]
    logger.info("Running Ghostscript tiffsep: pdf=%s dpi=%s output=%s", pdf_path, dpi, output_dir)
    logger.debug("Ghostscript command: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip()
        logger.error("Ghostscript failed with code %s: %s", proc.returncode, details)
        raise RuntimeError(f"Ghostscript завершился с ошибкой {proc.returncode}:\n{details}")
    tiffs = sorted(output_dir.glob("sep_*.tif"))
    logger.info("Ghostscript created %s TIFF files", len(tiffs))
    return tiffs


def classify_plate(path: Path) -> tuple[str, str]:
    low_name = path.name.lower()
    match = PAREN_NAME_PAT.search(low_name)
    if match:
        inner = match.group(1).strip()
        if inner == "cyan":
            return "C", "C"
        if inner == "magenta":
            return "M", "M"
        if inner == "yellow":
            return "Y", "Y"
        if inner == "black":
            return "K", "K"
        original = PAREN_NAME_PAT.search(path.name)
        return "SPOT", original.group(1).strip() if original else path.stem
    if re.search(r"sep_\d{3}\.tif$", low_name):
        return "COMPOSITE", path.name
    return "UNKNOWN", path.name


def tiff_sum_and_count_inverted(tiff_path: Path) -> tuple[int, int]:
    with Image.open(tiff_path) as image:
        if image.mode != "L":
            image = image.convert("L")
        arr = np.asarray(image, dtype=np.uint8)
    inverted = 255 - arr
    return int(inverted.sum()), int(inverted.size)


def calculate_pdf_coverage(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    progress: ProgressCallback | None = None,
) -> CoverageResult:
    pdf_path = Path(pdf_path)
    output_root = Path(output_root)
    logger.info("Coverage calculation started: pdf=%s dpi=%s output_root=%s", pdf_path, dpi, output_root)

    if dpi <= 0:
        logger.warning("Invalid DPI value: %s", dpi)
        raise ValueError("DPI должен быть положительным числом.")
    if not pdf_path.exists():
        logger.warning("PDF file does not exist: %s", pdf_path)
        raise FileNotFoundError(f"PDF не найден: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        logger.warning("Selected file is not a PDF: %s", pdf_path)
        raise ValueError("Выберите файл PDF.")

    if progress:
        progress("Поиск Ghostscript...")
    gs_path = find_ghostscript()

    if progress:
        progress("Создание папки вывода...")
    output_dir = make_output_dir(output_root)

    if progress:
        progress("Генерация цветоделения...")
    tiffs = run_tiffsep(gs_path, pdf_path, output_dir, dpi)
    if not tiffs:
        logger.error("Ghostscript did not create separation files: %s", output_dir)
        raise RuntimeError(f"Ghostscript не создал файлов цветоделения. Папка: {output_dir}")

    if progress:
        progress("Расчёт покрытия...")
    sums: dict[str, int] = {}
    counts: dict[str, int] = {}
    kinds: dict[str, str] = {}

    for tiff in tiffs:
        kind, label = classify_plate(tiff)
        if kind == "COMPOSITE":
            continue
        total, count = tiff_sum_and_count_inverted(tiff)
        logger.debug("Plate measured: file=%s kind=%s label=%s pixels=%s", tiff, kind, label, count)
        sums[label] = sums.get(label, 0) + total
        counts[label] = counts.get(label, 0) + count
        kinds[label] = kind

    order = {"C": 0, "M": 1, "Y": 2, "K": 3}
    labels = sorted(sums, key=lambda value: (order.get(value, 100), value.lower()))
    plates = [
        PlateCoverage(
            name=label,
            percent=(sums[label] / (counts[label] * 255.0)) * 100.0,
            kind=kinds.get(label, "UNKNOWN"),
        )
        for label in labels
    ]
    logger.info(
        "Coverage calculation finished: pdf=%s plates=%s output_dir=%s",
        pdf_path,
        {plate.name: round(plate.percent, 4) for plate in plates},
        output_dir,
    )
    return CoverageResult(pdf_path=pdf_path, output_dir=output_dir, plates=plates)
