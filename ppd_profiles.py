# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re

from halftone import ScreenSpec


logger = logging.getLogger(__name__)

PROCESS_PLATES = {
    "ProcessCyan": "C",
    "ProcessMagenta": "M",
    "ProcessYellow": "Y",
    "ProcessBlack": "K",
    "CustomColor": "Spot",
}

SUPPORTED_DOT_SHAPES = {
    "c": ("Круглая", "circle"),
    "r": ("Круглая Fogra", "circle"),
    "e": ("Эллиптическая", "ellipse"),
    "s": ("Квадратная", "square"),
    "l": ("Линейная", "line"),
}


@dataclass(frozen=True)
class ScreenPreset:
    dpi: int
    frequency_lpi: float
    screens: dict[str, ScreenSpec]

    @property
    def label(self) -> str:
        return f"{self.frequency_lpi:g} lpi / {self.dpi} dpi"


@dataclass(frozen=True)
class PpdProfile:
    path: Path
    name: str
    manufacturer: str
    product: str
    resolutions: tuple[int, ...]
    presets: tuple[ScreenPreset, ...]
    dot_shapes: tuple[tuple[str, str, str], ...]
    default_resolution: int | None
    default_dot_shape: str

    def frequencies_for_dpi(self, dpi: int) -> tuple[float, ...]:
        return tuple(sorted({preset.frequency_lpi for preset in self.presets if preset.dpi == dpi}))

    def screen_specs(self, dpi: int, frequency_lpi: float) -> dict[str, ScreenSpec]:
        candidates = [preset for preset in self.presets if preset.dpi == dpi]
        if not candidates:
            return {}
        return min(candidates, key=lambda preset: abs(preset.frequency_lpi - frequency_lpi)).screens


def discover_ppd_profiles(root: Path) -> list[PpdProfile]:
    profiles: list[PpdProfile] = []
    seen: set[Path] = set()
    for pattern in ("*.ppd", "*.PPD"):
        for path in sorted(root.rglob(pattern)):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                profiles.append(parse_ppd(path))
            except Exception:
                logger.exception("Failed to parse PPD profile: %s", path)
    return profiles


def parse_ppd(path: Path) -> PpdProfile:
    text = path.read_text(encoding="latin-1", errors="replace")
    name = _quoted_value(text, "NickName") or _quoted_value(text, "ModelName") or path.stem
    manufacturer = _quoted_value(text, "Manufacturer") or ""
    product = _quoted_value(text, "Product") or ""

    resolutions = tuple(sorted({int(value) for value in re.findall(r"^\*Resolution\s+(\d+)dpi(?:[/\s:])", text, re.MULTILINE)}))
    default_resolution_match = re.search(r"^\*DefaultResolution:\s*(\d+)dpi", text, re.MULTILINE)
    default_resolution = int(default_resolution_match.group(1)) if default_resolution_match else None

    default_dot_match = re.search(r"^\*DefaultBCDotShape:\s*(\S+)", text, re.MULTILINE)
    default_dot_shape = default_dot_match.group(1) if default_dot_match else "c"
    dot_shapes = _parse_dot_shapes(text)
    presets = _parse_screen_presets(text)

    logger.info(
        "PPD profile loaded: path=%s name=%s resolutions=%s presets=%s dot_shapes=%s",
        path,
        name,
        len(resolutions),
        len(presets),
        len(dot_shapes),
    )
    return PpdProfile(
        path=path,
        name=name,
        manufacturer=manufacturer,
        product=product.strip("()"),
        resolutions=resolutions,
        presets=presets,
        dot_shapes=dot_shapes,
        default_resolution=default_resolution,
        default_dot_shape=default_dot_shape,
    )


def _quoted_value(text: str, key: str) -> str | None:
    match = re.search(rf"^\*{re.escape(key)}:\s*\"([^\"]*)\"", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_dot_shapes(text: str) -> tuple[tuple[str, str, str], ...]:
    found: list[tuple[str, str, str]] = []
    for match in re.finditer(r"^\*BCDotShape\s+(\S+)/([^:]+):", text, re.MULTILINE):
        ppd_code = match.group(1)
        supported = SUPPORTED_DOT_SHAPES.get(ppd_code)
        if supported is None:
            continue
        label, engine_code = supported
        if not any(item[2] == engine_code for item in found):
            found.append((ppd_code, label, engine_code))
    if not found:
        found.append(("c", "Круглая", "circle"))
    return tuple(found)


def _parse_screen_presets(text: str) -> tuple[ScreenPreset, ...]:
    values: dict[tuple[int, float], dict[str, dict[str, float]]] = {}
    pattern = re.compile(
        r"^\*ColorSepScreen(?P<kind>Angle|Freq)\s+"
        r"(?P<plate>ProcessCyan|ProcessMagenta|ProcessYellow|ProcessBlack|CustomColor)"
        r"\.(?P<frequency>\d+(?:[.,]\d+)?)lpi\.(?P<dpi>\d+)dpi[^:]*:\s*"
        r"\"(?P<value>[-+]?\d+(?:[.,]\d+)?)\"",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        frequency = _number(match.group("frequency"))
        dpi = int(match.group("dpi"))
        plate = PROCESS_PLATES[match.group("plate")]
        kind = match.group("kind").lower()
        values.setdefault((dpi, frequency), {}).setdefault(plate, {})[kind] = _number(match.group("value"))

    presets: list[ScreenPreset] = []
    for (dpi, frequency), plate_values in sorted(values.items()):
        screens = {
            plate: ScreenSpec(frequency_lpi=data["freq"], angle_deg=data["angle"])
            for plate, data in plate_values.items()
            if "freq" in data and "angle" in data
        }
        if screens:
            presets.append(ScreenPreset(dpi=dpi, frequency_lpi=frequency, screens=screens))
    return tuple(presets)


def _number(value: str) -> float:
    return float(value.replace(",", "."))
