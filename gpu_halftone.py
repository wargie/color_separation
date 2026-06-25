# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
from threading import Lock

import numpy as np

from halftone import halftone_cell_size


logger = logging.getLogger(__name__)

_KERNEL_SOURCE = r"""
#define PI_F 3.14159265358979323846f

float spot_threshold(float distance) {
    float radius_sq = distance * distance;
    if (distance <= 0.5f) {
        return clamp(PI_F * radius_sq, 0.0f, 1.0f);
    }
    float segment = radius_sq * acos(0.5f / distance);
    segment -= 0.5f * sqrt(fmax(radius_sq - 0.25f, 0.0f));
    return clamp(PI_F * radius_sq - 4.0f * segment, 0.0f, 1.0f);
}

float random_threshold(uint x, uint y) {
    uint value = x * 374761393u + y * 668265263u;
    value = (value ^ (value >> 13u)) * 1274126177u;
    value = value ^ (value >> 16u);
    return convert_float(value) / 4294967295.0f;
}
float shape_threshold(float cell_x, float cell_y, int spot_shape) {
    if (spot_shape == 2) {
        float extent = fmax(fabs(cell_x), fabs(cell_y));
        return clamp(4.0f * extent * extent, 0.0f, 1.0f);
    }
    if (spot_shape == 3) {
        return clamp(2.0f * fabs(cell_y), 0.0f, 1.0f);
    }
    float shape_x = spot_shape == 1 ? cell_x * 0.75f : cell_x;
    float shape_y = spot_shape == 1 ? cell_y / 0.75f : cell_y;
    return spot_threshold(sqrt(shape_x * shape_x + shape_y * shape_y));
}

__kernel void halftone(
    __global const uchar *gray,
    __global uchar *output,
    const int width,
    const int height,
    const float cell_size,
    const float angle_rad,
    const int mode,
    const int spot_shape
) {
    int x = get_global_id(0);
    int y = get_global_id(1);
    if (x >= width || y >= height) {
        return;
    }

    int index = y * width + x;
    uchar source = gray[index];

    // Preserve paper and 100% solids, including tiny conversion noise.
    if (source >= (uchar)254) {
        output[index] = (uchar)255;
        return;
    }
    if (source <= (uchar)8) {
        output[index] = (uchar)0;
        return;
    }

    float ink = (255.0f - convert_float(source)) / 255.0f;
    if (mode == 4 && ink > 0.0f && ink < 0.02f) {
        ink = 0.02f;
    }
    float noise = random_threshold((uint)x, (uint)y);
    int use_fm = mode == 2 || (mode == 3 && (ink < 0.20f || ink > 0.85f));

    if (use_fm) {
        output[index] = noise < ink ? (uchar)0 : (uchar)255;
        return;
    }

    float cos_a = cos(angle_rad);
    float sin_a = sin(angle_rad);
    float rotated_x = convert_float(x) * cos_a + convert_float(y) * sin_a;
    float rotated_y = -convert_float(x) * sin_a + convert_float(y) * cos_a;
    float cell_x = rotated_x / cell_size;
    float cell_y = rotated_y / cell_size;
    cell_x = cell_x - floor(cell_x) - 0.5f;
    cell_y = cell_y - floor(cell_y) - 0.5f;
    float threshold = shape_threshold(cell_x, cell_y, spot_shape);
    output[index] = threshold <= ink ? (uchar)0 : (uchar)255;
}
"""


class OpenCLHalftoneBackend:
    def __init__(self) -> None:
        import pyopencl as cl

        devices = [
            device
            for platform in cl.get_platforms()
            for device in platform.get_devices()
            if device.type & cl.device_type.GPU
        ]
        if not devices:
            raise RuntimeError("OpenCL GPU device was not found")

        self.cl = cl
        self.device = devices[0]
        self.context = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.context)
        self.program = cl.Program(self.context, _KERNEL_SOURCE).build()
        self.kernel = cl.Kernel(self.program, "halftone")
        self.execution_lock = Lock()
        self.name = f"OpenCL GPU: {self.device.name.strip()}"

    def apply(
        self,
        gray: np.ndarray,
        *,
        mode: int,
        dpi: float,
        frequency_lpi: float,
        angle_deg: float,
        spot_shape: int = 0,
    ) -> np.ndarray:
        source = np.ascontiguousarray(gray, dtype=np.uint8)
        output = np.empty_like(source)
        height, width = source.shape
        cell_size = halftone_cell_size(dpi, frequency_lpi)

        cl = self.cl
        flags = cl.mem_flags
        source_buffer = cl.Buffer(
            self.context,
            flags.READ_ONLY | flags.COPY_HOST_PTR,
            hostbuf=source,
        )
        output_buffer = cl.Buffer(self.context, flags.WRITE_ONLY, output.nbytes)
        with self.execution_lock:
            self.kernel.set_args(
                source_buffer,
                output_buffer,
                np.int32(width),
                np.int32(height),
                np.float32(cell_size),
                np.float32(np.deg2rad(angle_deg)),
                np.int32(mode),
                np.int32(spot_shape),
            )
            cl.enqueue_nd_range_kernel(self.queue, self.kernel, (width, height), None)
            cl.enqueue_copy(self.queue, output, output_buffer).wait()
        return output


_backend: OpenCLHalftoneBackend | None = None
_backend_error: str | None = None
_backend_lock = Lock()


def get_opencl_backend() -> OpenCLHalftoneBackend | None:
    global _backend, _backend_error
    if _backend is not None or _backend_error is not None:
        return _backend

    with _backend_lock:
        if _backend is not None or _backend_error is not None:
            return _backend
        try:
            _backend = OpenCLHalftoneBackend()
            logger.info("GPU halftone backend initialized: %s", _backend.name)
        except Exception as exc:
            _backend_error = str(exc)
            logger.warning("GPU halftone backend unavailable, using CPU: %s", exc)
    return _backend


def compute_backend_name() -> str:
    backend = get_opencl_backend()
    return backend.name if backend else "CPU NumPy"
