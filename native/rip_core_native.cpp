#include "rip_core_native.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace {

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr uint8_t kNoDot = 0;
constexpr uint8_t kDot = 255;

float clamp01(float value) {
    return std::max(0.0f, std::min(1.0f, value));
}

float random_threshold(uint32_t x, uint32_t y) {
    uint32_t value = x * 374761393u + y * 668265263u;
    value = (value ^ (value >> 13u)) * 1274126177u;
    value = value ^ (value >> 16u);
    return static_cast<float>(value) / 4294967295.0f;
}

float circle_threshold(float distance) {
    const float radius_sq = distance * distance;
    if (distance <= 0.5f) {
        return clamp01(static_cast<float>(kPi) * radius_sq);
    }
    float segment = radius_sq * std::acos(0.5f / distance);
    segment -= 0.5f * std::sqrt(std::max(radius_sq - 0.25f, 0.0f));
    return clamp01(static_cast<float>(kPi) * radius_sq - 4.0f * segment);
}

float shape_threshold(float cell_x, float cell_y, int32_t dot_shape) {
    if (dot_shape == RIP_DOT_SQUARE) {
        const float extent = std::max(std::abs(cell_x), std::abs(cell_y));
        return clamp01(4.0f * extent * extent);
    }
    if (dot_shape == RIP_DOT_LINE) {
        return clamp01(2.0f * std::abs(cell_y));
    }
    const float shape_x = dot_shape == RIP_DOT_ELLIPSE ? cell_x * 0.75f : cell_x;
    const float shape_y = dot_shape == RIP_DOT_ELLIPSE ? cell_y / 0.75f : cell_y;
    return circle_threshold(std::sqrt(shape_x * shape_x + shape_y * shape_y));
}

bool validate_params(const RipTileParams* params) {
    if (params == nullptr) {
        return false;
    }
    if (params->width == 0 || params->height == 0) {
        return false;
    }
    if (params->input_stride < params->width || params->output_stride < params->width) {
        return false;
    }
    if (params->dpi <= 0.0 || params->lpi <= 0.0) {
        return false;
    }
    return true;
}

uint8_t screen_sample(uint8_t source, uint32_t x, uint32_t y, const RipTileParams& params) {
    if (source >= 254) {
        return kNoDot;
    }
    if (source <= 8) {
        return kDot;
    }

    float ink = (255.0f - static_cast<float>(source)) / 255.0f;
    if (params.algorithm == RIP_ALGORITHM_FLEXO && ink > 0.0f && ink < static_cast<float>(params.min_dot)) {
        ink = static_cast<float>(params.min_dot);
    }

    const uint32_t absolute_x = params.tile_x + x;
    const uint32_t absolute_y = params.tile_y + y;
    const float noise = random_threshold(absolute_x, absolute_y);
    const bool use_fm =
        params.algorithm == RIP_ALGORITHM_FM ||
        params.algorithm == RIP_ALGORITHM_ERROR_DIFFUSION ||
        (params.algorithm == RIP_ALGORITHM_HYBRID && (ink < 0.20f || ink > 0.85f));

    if (use_fm) {
        return noise < ink ? kDot : kNoDot;
    }

    const float cell_size = static_cast<float>(params.dpi / params.lpi);
    const float angle_rad = static_cast<float>(params.angle_deg * kPi / 180.0);
    const float cos_a = std::cos(angle_rad);
    const float sin_a = std::sin(angle_rad);
    const float px = static_cast<float>(absolute_x);
    const float py = static_cast<float>(absolute_y);
    const float rotated_x = px * cos_a + py * sin_a;
    const float rotated_y = -px * sin_a + py * cos_a;
    float cell_x = rotated_x / cell_size;
    float cell_y = rotated_y / cell_size;
    cell_x = cell_x - std::floor(cell_x) - 0.5f;
    cell_y = cell_y - std::floor(cell_y) - 0.5f;

    const float threshold = shape_threshold(cell_x, cell_y, params.dot_shape);
    return threshold <= ink ? kDot : kNoDot;
}

} // namespace

extern "C" {

RIP_CORE_API RipCoreVersion rip_core_version() {
    return RipCoreVersion{0, 3, 0};
}

RIP_CORE_API RipStatus rip_screen_tile(
    const uint8_t* gray_input,
    uint8_t* bit_output,
    const RipTileParams* params
) {
    if (gray_input == nullptr || bit_output == nullptr || !validate_params(params)) {
        return RIP_STATUS_INVALID_ARGUMENT;
    }

    const RipTileParams& p = *params;
    switch (p.algorithm) {
        case RIP_ALGORITHM_NONE:
        case RIP_ALGORITHM_AM:
        case RIP_ALGORITHM_FM:
        case RIP_ALGORITHM_HYBRID:
        case RIP_ALGORITHM_FLEXO:
        case RIP_ALGORITHM_ERROR_DIFFUSION:
            break;
        default:
            return RIP_STATUS_UNSUPPORTED;
    }

    if (p.dot_shape < RIP_DOT_CIRCLE || p.dot_shape > RIP_DOT_LINE) {
        return RIP_STATUS_UNSUPPORTED;
    }

    for (uint32_t y = 0; y < p.height; ++y) {
        const uint8_t* input_row = gray_input + y * p.input_stride;
        uint8_t* output_row = bit_output + y * p.output_stride;
        for (uint32_t x = 0; x < p.width; ++x) {
            if (p.algorithm == RIP_ALGORITHM_NONE) {
                output_row[x] = input_row[x] <= 127 ? kDot : kNoDot;
            } else {
                output_row[x] = screen_sample(input_row[x], x, y, p);
            }
        }
    }

    return RIP_STATUS_OK;
}

}