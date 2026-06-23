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

from halftone import ScreenSpec, extract_postscript_screen_angles


# Separation TIFFs are generated locally by Ghostscript and can legitimately
# exceed Pillow's generic decompression-bomb limit at 1200-2400 DPI.
Image.MAX_IMAGE_PIXELS = None


DEFAULT_DPI = 600
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "Separation"
SUPPORTED_INPUT_SUFFIXES = {".pdf", ".ps", ".eps"}
PAREN_NAME_PAT = re.compile(r"\((.+?)\)\.tif$", re.IGNORECASE)
SEP_PAGE_PAT = re.compile(r"sep_(\d{3})", re.IGNORECASE)
PLATE_COLOR_PAT = re.compile(r"^%%PlateColor:\s*(.+?)\s*$", re.IGNORECASE)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateCoverage:
    name: str
    percent: float
    kind: str
    tiff_path: Path | None = None


@dataclass(frozen=True)
class CoverageResult:
    pdf_path: Path
    source_paths: list[Path]
    output_dir: Path
    plates: list[PlateCoverage]
    screen_specs: dict[str, ScreenSpec]


ProgressCallback = Callable[[str], None]


def find_ghostscript() -> str:
    for name in ("gswin64c", "gswin64c.exe", "gswin32c", "gswin32c.exe", "gs"):
        path = shutil.which(name)
        if path:
            logger.info("Ghostscript found: %s", path)
            return path
    logger.error("Ghostscript executable was not found in PATH")
    raise RuntimeError("Ghostscript не найден. Установите Ghostscript и добавьте gswin64c в PATH.")


def first_supported_file_near_script() -> Path | None:
    files = [
        path
        for path in Path(__file__).resolve().parent.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
    ]
    return sorted(files)[0] if files else None


def first_pdf_near_script() -> Path | None:
    return first_supported_file_near_script()


def make_output_dir(output_root: Path) -> Path:
    output_dir = output_root / f"temp_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory created: %s", output_dir)
    return output_dir


def run_tiffsep(gs_path: str, source_path: Path, output_dir: Path, dpi: int) -> list[Path]:
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
        str(source_path),
    ]
    logger.info("Running Ghostscript tiffsep: source=%s dpi=%s output=%s", source_path, dpi, output_dir)
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


def normalize_plate_name(name: str) -> tuple[str, str]:
    clean_name = name.strip().lstrip("/")
    normalized = re.sub(r"[^a-z0-9]+", " ", clean_name.lower()).strip()
    words = set(normalized.split())

    if normalized == "c" or "cyan" in words:
        return "C", "C"
    if normalized == "m" or "magenta" in words:
        return "M", "M"
    if normalized == "y" or "yellow" in words:
        return "Y", "Y"
    if normalized == "k" or "black" in words:
        return "K", "K"
    if "pantone" in words or "pms" in words:
        return "SPOT", clean_name
    return "UNKNOWN", clean_name


def infer_separated_plate_from_source(source_path: Path) -> tuple[str, str]:
    return normalize_plate_name(source_path.stem)


def extract_postscript_plate_colors(source_path: Path) -> list[tuple[str, str]]:
    if source_path.suffix.lower() not in {".ps", ".eps"}:
        return []

    plate_colors: list[tuple[str, str]] = []
    try:
        with source_path.open("r", encoding="latin-1", errors="replace") as handle:
            for line in handle:
                match = PLATE_COLOR_PAT.match(line)
                if match:
                    plate_colors.append(normalize_plate_name(match.group(1)))
    except OSError:
        logger.exception("Failed to read PostScript plate colors: %s", source_path)
        return []

    logger.info("PostScript plate colors extracted: source=%s colors=%s", source_path, plate_colors)
    return plate_colors


def sep_page_index(tiff_path: Path) -> int | None:
    match = SEP_PAGE_PAT.search(tiff_path.name)
    if not match:
        return None
    return int(match.group(1))


def tiff_sum_and_count_inverted(tiff_path: Path) -> tuple[int, int]:
    with Image.open(tiff_path) as image:
        if image.mode != "L":
            image = image.convert("L")
        histogram = image.histogram()
        count = image.width * image.height
    total = sum((255 - level) * pixels for level, pixels in enumerate(histogram))
    return total, count


def _validate_source_path(source_path: Path) -> None:
    if not source_path.exists():
        logger.warning("Input file does not exist: %s", source_path)
        raise FileNotFoundError(f"Файл не найден: {source_path}")
    if source_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        logger.warning("Unsupported input file format: %s", source_path)
        raise ValueError("Выберите файл PDF, PS или EPS.")


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return cleaned or "plate"


def _measure_tiffs(
    tiffs: list[Path],
    source_path: Path,
    sums: dict[str, int],
    counts: dict[str, int],
    kinds: dict[str, str],
    plate_paths: dict[str, Path],
) -> tuple[set[Path], dict[Path, str]]:
    source_is_separated_ps = source_path.suffix.lower() in {".ps", ".eps"}
    ps_plate_colors = extract_postscript_plate_colors(source_path)
    composite_tiffs: list[Path] = []
    measured_named_plates = 0
    used_tiffs: set[Path] = set()
    rename_labels: dict[Path, str] = {}

    for tiff in tiffs:
        kind, label = classify_plate(tiff)
        if kind == "COMPOSITE":
            composite_tiffs.append(tiff)
            continue

        total, count = tiff_sum_and_count_inverted(tiff)
        if source_is_separated_ps and total == 0:
            logger.debug("Skipping empty separated PS plate: file=%s kind=%s label=%s", tiff, kind, label)
            continue
        page_index = sep_page_index(tiff)
        if source_is_separated_ps and page_index and page_index <= len(ps_plate_colors):
            kind, label = ps_plate_colors[page_index - 1]
            logger.debug("Mapped separated PS page to plate color: file=%s page=%s label=%s", tiff, page_index, label)
            rename_labels[tiff] = label

        logger.debug("Plate measured: file=%s kind=%s label=%s pixels=%s", tiff, kind, label, count)
        sums[label] = sums.get(label, 0) + total
        counts[label] = counts.get(label, 0) + count
        kinds[label] = kind
        plate_paths[label] = tiff
        measured_named_plates += 1
        used_tiffs.add(tiff)

    if not source_is_separated_ps or measured_named_plates:
        return used_tiffs, rename_labels

    for tiff in composite_tiffs:
        kind, label = infer_separated_plate_from_source(source_path)
        logger.info("Using composite TIFF as separated PS fallback: source=%s label=%s", source_path, label)
        total, count = tiff_sum_and_count_inverted(tiff)
        if total == 0:
            logger.debug("Skipping empty separated PS composite fallback: file=%s label=%s", tiff, label)
            continue
        sums[label] = sums.get(label, 0) + total
        counts[label] = counts.get(label, 0) + count
        kinds[label] = kind
        plate_paths[label] = tiff
        used_tiffs.add(tiff)
        rename_labels[tiff] = label
    return used_tiffs, rename_labels


def cleanup_unused_tiffs(tiffs: list[Path], used_tiffs: set[Path]) -> None:
    used_resolved = {path.resolve() for path in used_tiffs}
    for tiff in tiffs:
        if tiff.resolve() in used_resolved:
            continue
        try:
            tiff.unlink()
            logger.info("Removed unused separation TIFF: %s", tiff)
        except OSError:
            logger.exception("Failed to remove unused separation TIFF: %s", tiff)


def rename_used_tiffs(rename_labels: dict[Path, str]) -> dict[Path, Path]:
    renamed_paths: dict[Path, Path] = {}
    used_targets: set[Path] = set()
    for source_path, label in rename_labels.items():
        if not source_path.exists():
            renamed_paths[source_path] = source_path
            continue
        target = source_path.with_name(f"{safe_filename_part(label)}.tif")
        if target == source_path:
            renamed_paths[source_path] = source_path
            continue
        if target.exists() or target in used_targets:
            stem = target.stem
            counter = 2
            while target.exists() or target in used_targets:
                target = source_path.with_name(f"{stem}_{counter}.tif")
                counter += 1
        try:
            source_path.rename(target)
            renamed_paths[source_path] = target
            used_targets.add(target)
            logger.info("Renamed separation TIFF: %s -> %s", source_path, target)
        except OSError:
            logger.exception("Failed to rename separation TIFF: %s", source_path)
            renamed_paths[source_path] = source_path
    return renamed_paths


def calculate_sources_coverage(
    source_paths: list[Path],
    dpi: int = DEFAULT_DPI,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    progress: ProgressCallback | None = None,
) -> CoverageResult:
    source_paths = [Path(path) for path in source_paths]
    output_root = Path(output_root)
    logger.info("Coverage calculation started: sources=%s dpi=%s output_root=%s", source_paths, dpi, output_root)

    if dpi <= 0:
        logger.warning("Invalid DPI value: %s", dpi)
        raise ValueError("DPI должен быть положительным числом.")
    if not source_paths:
        logger.warning("Coverage calculation requested without input files")
        raise ValueError("Выберите хотя бы один файл PDF, PS или EPS.")

    for source_path in source_paths:
        _validate_source_path(source_path)

    if progress:
        progress("Поиск Ghostscript...")
    gs_path = find_ghostscript()

    if progress:
        progress("Создание папки вывода...")
    output_dir = make_output_dir(output_root)

    sums: dict[str, int] = {}
    counts: dict[str, int] = {}
    kinds: dict[str, str] = {}
    plate_paths: dict[str, Path] = {}
    screen_specs: dict[str, ScreenSpec] = {}
    all_tiffs: list[Path] = []
    used_tiffs: set[Path] = set()
    rename_labels: dict[Path, str] = {}

    for index, source_path in enumerate(source_paths, start=1):
        screen_specs.update(extract_postscript_screen_angles(source_path))
        if progress:
            progress(f"Генерация цветоделения {index}/{len(source_paths)}...")
        source_output_dir = output_dir if len(source_paths) == 1 else output_dir / f"{index:03d}_{source_path.stem}"
        tiffs = run_tiffsep(gs_path, source_path, source_output_dir, dpi)
        if not tiffs:
            logger.error("Ghostscript did not create separation files: %s", source_output_dir)
            raise RuntimeError(f"Ghostscript не создал файлов цветоделения. Папка: {source_output_dir}")

        if progress:
            progress(f"Расчёт покрытия {index}/{len(source_paths)}...")
        all_tiffs.extend(tiffs)
        source_used_tiffs, source_rename_labels = _measure_tiffs(tiffs, source_path, sums, counts, kinds, plate_paths)
        used_tiffs.update(source_used_tiffs)
        rename_labels.update(source_rename_labels)

    if not sums:
        logger.error("No measurable plates were found: sources=%s output_dir=%s", source_paths, output_dir)
        raise RuntimeError(f"Не найдено измеримых цветовых пластин. Папка: {output_dir}")

    cleanup_unused_tiffs(all_tiffs, used_tiffs)
    renamed_paths = rename_used_tiffs(rename_labels)
    plate_paths = {label: renamed_paths.get(path, path) for label, path in plate_paths.items()}

    order = {"C": 0, "M": 1, "Y": 2, "K": 3}
    labels = sorted(sums, key=lambda value: (order.get(value, 100), value.lower()))
    plates = [
        PlateCoverage(
            name=label,
            percent=(sums[label] / (counts[label] * 255.0)) * 100.0,
            kind=kinds.get(label, "UNKNOWN"),
            tiff_path=plate_paths.get(label),
        )
        for label in labels
    ]

    logger.info(
        "Coverage calculation finished: sources=%s plates=%s output_dir=%s",
        source_paths,
        {plate.name: round(plate.percent, 4) for plate in plates},
        output_dir,
    )
    return CoverageResult(
        pdf_path=source_paths[0],
        source_paths=source_paths,
        output_dir=output_dir,
        plates=plates,
        screen_specs=screen_specs,
    )


def calculate_pdf_coverage(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    progress: ProgressCallback | None = None,
) -> CoverageResult:
    return calculate_sources_coverage([Path(pdf_path)], dpi=dpi, output_root=output_root, progress=progress)
