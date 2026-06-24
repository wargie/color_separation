#include "rip_core_native.h"

extern "C" {

RIP_CORE_API RipCoreVersion rip_core_version() {
    return RipCoreVersion{0, 1, 0};
}

}
