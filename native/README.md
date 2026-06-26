# Native RIP Backend Contract

This directory contains the C/C++ ABI boundary for the heavy pixel-processing layer.
Python remains the workflow and reference layer; native code is responsible for work that cannot safely be done by loading full production-size plates into NumPy arrays.

## Target pipeline

```text
PS/PDF/EPS
  -> Ghostscript / separation frontend
  -> CMYK + spot TIFF separations
  -> TIFF inspection / separation preview
  -> compensation curves / minimum-dot checks
  -> 1-bit or limited-tone output
```

## Language split

Python owns:

- GUI and job workflow;
- Ghostscript invocation;
- PPD/profile parsing;
- recipe, curve and setting management;
- reference halftone implementation for tests;
- visual preview orchestration.

C++ or Rust owns:

- tiled/striped processing of large TIFF files;
- AM/FM/XM screening inner loops;
- minimum-dot and solid preservation logic at production resolution;
- memory-mapped or streaming IO;
- true 1-bit TIFF writing through libtiff or an equivalent backend.

## ABI rules

The public ABI is C-compatible and lives in `rip_core_native.h`.
The first stable primitive is `rip_screen_tile`:

```c
RipStatus rip_screen_tile(
    const uint8_t* gray_input,
    uint8_t* bit_output,
    const RipTileParams* params
);
```

Input convention:

- `0` means full ink;
- `255` means paper;
- intermediate values are coverage masks.

Initial output convention:

- `0` means no dot;
- `255` means dot.

A production TIFF writer can later pack this byte mask into true 1-bit strips. Keeping the tile primitive byte-addressable makes Python tests and debugging much easier.

## Memory model

Production files must not be loaded as a full sheet. A 600 x 400 mm plate at 2400 dpi is roughly 56,688 x 37,800 pixels, or about 2.14 GB for one 8-bit grayscale channel before any temporary buffers.

Native processing must therefore use one of these modes:

- tile processing, typically 512 x 512 or 1024 x 1024;
- stripe processing, typically a few hundred rows;
- memory-mapped TIFF access;
- streaming read/write with bounded scratch buffers.

Temporary memory should be proportional to tile/stripe size, not sheet size.

## Solid and paper policy

Halftone algorithms must preserve:

- paper areas at or near 255;
- 100% solids at or near 0;
- already bitonal plates unless an explicit rescreen mode is requested.

AM/FM/XM screening is for intermediate tones only. This is required for flexo/offset preview and for production-safe plate processing.

## Python integration

`native_backend.py` is the Python facade. It discovers `rip_core_native.dll` via:

1. `RIP_CORE_NATIVE_DLL` environment variable;
2. `native/rip_core_native.dll` next to the Python project.

`RIP_BACKEND` controls selection:

- `auto` - use native DLL if available, otherwise Python reference;
- `native` - require/identify the native path;
- `python_reference` - force Python reference processing.

Tile and stripe sizes are controlled by:

- `RIP_TILE_SIZE`;
- `RIP_STRIPE_HEIGHT`;
- `RIP_MEMORY_MAP`.

## Current state

The current C++ implementation exports the ABI and contains a first working `rip_screen_tile` loop for AM, FM, hybrid, flexo and error-diffusion style screening. It preserves paper and solids and writes a byte-addressable dot mask that can later be packed into true 1-bit TIFF strips. The Python renderer remains the visual reference implementation while the native backend grows into the production path.
## Build

LLVM/clang can be installed with winget on Windows:

```powershell
winget install --id LLVM.LLVM --exact --accept-package-agreements --accept-source-agreements
```

Build the native DLL from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\native\build_native.ps1
```

The script tries CMake first, then direct `cl`, `clang++` or `g++`. The output is copied to:

```text
native/rip_core_native.dll
```