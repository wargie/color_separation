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

RIP_CORE_API RipCoreVersion rip_core_version();

}
