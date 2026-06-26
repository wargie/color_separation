# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)

NATIVE_ENV_VAR = "RIP_CORE_NATIVE_DLL"
DEFAULT_NATIVE_DLL = Path(__file__).resolve().parent / "native" / "rip_core_native.dll"

BACKEND_PYTHON_REFERENCE = "python_reference"
BACKEND_NATIVE = "native"
BACKEND_AUTO = "auto"

ALGORITHM_NONE = 0
ALGORITHM_AM = 1
ALGORITHM_FM = 2
ALGORITHM_HYBRID = 3
ALGORITHM_FLEXO = 4
ALGORITHM_ERROR_DIFFUSION = 5

DOT_CIRCLE = 0
DOT_ELLIPSE = 1
DOT_SQUARE = 2
DOT_LINE = 3

STATUS_OK = 0
STATUS_UNSUPPORTED = 1
STATUS_INVALID_ARGUMENT = 2
STATUS_NOT_IMPLEMENTED = 3
STATUS_IO_ERROR = 4
STATUS_INTERNAL_ERROR = 5


class RipCoreVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint32),
        ("minor", ctypes.c_uint32),
        ("patch", ctypes.c_uint32),
    ]


class RipTileParams(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("input_stride", ctypes.c_uint32),
        ("output_stride", ctypes.c_uint32),
        ("tile_x", ctypes.c_uint32),
        ("tile_y", ctypes.c_uint32),
        ("dpi", ctypes.c_double),
        ("lpi", ctypes.c_double),
        ("angle_deg", ctypes.c_double),
        ("min_dot", ctypes.c_double),
        ("algorithm", ctypes.c_int32),
        ("dot_shape", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class NativeBackendInfo:
    dll_path: Path
    available: bool
    version: str | None = None
    reason: str | None = None

    @property
    def label(self) -> str:
        if self.available:
            return f"Native RIP core {self.version}: {self.dll_path}"
        suffix = f" ({self.reason})" if self.reason else ""
        return f"Python reference renderer/backend{suffix}"


@dataclass(frozen=True)
class BackendConfig:
    mode: str = BACKEND_AUTO
    tile_size: int = 512
    stripe_height: int = 512
    prefer_memory_map: bool = True

    @classmethod
    def from_environment(cls) -> "BackendConfig":
        return cls(
            mode=os.environ.get("RIP_BACKEND", BACKEND_AUTO).strip().lower() or BACKEND_AUTO,
            tile_size=_env_int("RIP_TILE_SIZE", 512),
            stripe_height=_env_int("RIP_STRIPE_HEIGHT", 512),
            prefer_memory_map=os.environ.get("RIP_MEMORY_MAP", "1").strip().lower() not in {"0", "false", "no"},
        )


class NativeRipBackend:
    def __init__(self, dll_path: Path | None = None) -> None:
        self.dll_path = dll_path or native_library_path()
        self._dll: ctypes.CDLL | None = None
        self.info = self._load()

    def _load(self) -> NativeBackendInfo:
        if not self.dll_path.exists():
            return NativeBackendInfo(self.dll_path, False, reason="native DLL is not built")
        try:
            dll = ctypes.CDLL(str(self.dll_path))
            dll.rip_core_version.restype = RipCoreVersion
            dll.rip_screen_tile.argtypes = [
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(RipTileParams),
            ]
            dll.rip_screen_tile.restype = ctypes.c_int32
            self._dll = dll
            version = dll.rip_core_version()
            return NativeBackendInfo(
                self.dll_path,
                True,
                version=f"{version.major}.{version.minor}.{version.patch}",
            )
        except OSError as exc:
            logger.warning("Native RIP core could not be loaded: %s", exc)
            return NativeBackendInfo(self.dll_path, False, reason=str(exc))

    @property
    def available(self) -> bool:
        return self.info.available

    def supports_tile_screening(self) -> bool:
        return self._dll is not None and hasattr(self._dll, "rip_screen_tile")

    def screen_tile(self, gray: bytes, params: RipTileParams) -> bytes:
        if self._dll is None or not self.supports_tile_screening():
            raise RuntimeError("Native tile screening is unavailable")
        expected_input = params.input_stride * params.height
        expected_output = params.output_stride * params.height
        if len(gray) < expected_input:
            raise ValueError("Input tile buffer is smaller than input_stride * height")
        input_buffer = (ctypes.c_uint8 * len(gray)).from_buffer_copy(gray)
        output_buffer = (ctypes.c_uint8 * expected_output)()
        status = self._dll.rip_screen_tile(input_buffer, output_buffer, ctypes.byref(params))
        if status != STATUS_OK:
            raise RuntimeError(f"rip_screen_tile failed with status {status}")
        return bytes(output_buffer)


_native_backend: NativeRipBackend | None = None


def native_library_path() -> Path:
    configured = os.environ.get(NATIVE_ENV_VAR)
    return Path(configured) if configured else DEFAULT_NATIVE_DLL


def get_native_backend() -> NativeRipBackend:
    global _native_backend
    if _native_backend is None:
        _native_backend = NativeRipBackend()
    return _native_backend


def selected_backend_label(config: BackendConfig | None = None) -> str:
    config = config or BackendConfig.from_environment()
    native = get_native_backend()
    if config.mode == BACKEND_NATIVE:
        return native.info.label
    if config.mode == BACKEND_AUTO and native.available:
        return native.info.label
    return "Python reference renderer/backend"


def processing_plan_label(config: BackendConfig | None = None) -> str:
    config = config or BackendConfig.from_environment()
    backend = selected_backend_label(config)
    mmap = "mmap" if config.prefer_memory_map else "stream"
    return f"{backend}; tiles={config.tile_size}px; stripes={config.stripe_height}px; {mmap}"


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(1, value)
