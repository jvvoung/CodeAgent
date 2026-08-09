cmake_minimum_required(VERSION 3.20)
project(CppGrounding LANGUAGES CXX)
add_executable(cpp_grounding src/config_store.cpp)
target_compile_features(cpp_grounding PRIVATE cxx_std_17)
