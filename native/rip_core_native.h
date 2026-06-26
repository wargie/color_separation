#pragma once

#include <stdint.h>

#ifdef _WIN32
#define RIP_CORE_API __declspec(dllexport)
#else
#define RIP_CORE_API
#endif

extern "C" {

struct RipCoreVersion {
    uint32_t major;
    uint32_t minor;
    uint32_t patch;
};

enum RipStatus {
    RIP_STATUS_OK = 0,
    RIP_STATUS_UNSUPPORTED = 1,
    RIP_STATUS_INVALID_ARGUMENT = 2,
    RIP_STATUS_NOT_IMPLEMENTED = 3,
    RIP_STATUS_IO_ERROR = 4,
    RIP_STATUS_INTERNAL_ERROR = 5,
};

enum RipAlgorithm {
    RIP_ALGORITHM_NONE = 0,
    RIP_ALGORITHM_AM = 1,
    RIP_ALGORITHM_FM = 2,
    RIP_ALGORITHM_HYBRID = 3,
    RIP_ALGORITHM_FLEXO = 4,
    RIP_ALGORITHM_ERROR_DIFFUSION = 5,
};

enum RipDotShape {
    RIP_DOT_CIRCLE = 0,
    RIP_DOT_ELLIPSE = 1,
    RIP_DOT_SQUARE = 2,
    RIP_DOT_LINE = 3,
};

struct RipTileParams {
    uint32_t width;
    uint32_t height;
    uint32_t input_stride;
    uint32_t output_stride;
    uint32_t tile_x;
    uint32_t tile_y;
    double dpi;
    double lpi;
    double angle_deg;
    double min_dot;
    int32_t algorithm;
    int32_t dot_shape;
    uint32_t flags;
};

RIP_CORE_API RipCoreVersion rip_core_version();

// Screen one grayscale tile into a 1-bit-style byte mask.
// Input convention: 0 = full ink, 255 = paper.
// Output convention for the first implementation: 0 = no dot, 255 = dot.
// A later libtiff writer can pack this byte mask into true 1-bit strips.
RIP_CORE_API RipStatus rip_screen_tile(
    const uint8_t* gray_input,
    uint8_t* bit_output,
    const RipTileParams* params
);

}