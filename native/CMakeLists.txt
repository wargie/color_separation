cmake_minimum_required(VERSION 3.20)
project(rip_core_native LANGUAGES CXX)

add_library(rip_core_native SHARED rip_core_native.cpp)
target_compile_features(rip_core_native PRIVATE cxx_std_17)

if(MSVC)
    target_compile_options(rip_core_native PRIVATE /O2 /W4 /permissive-)
else()
    target_compile_options(rip_core_native PRIVATE -O3 -Wall -Wextra -Wpedantic)
endif()