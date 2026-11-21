cmake_minimum_required(VERSION 3.20...4.4)
project(${SKBUILD_PROJECT_NAME} LANGUAGES C CXX)

# Every vendored library is static and position-independent, so wheels need no
# system copy and no native symbol leaves the extension module.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)

option(EMBERLYN_SYSTEM_AWS_LC "Link an installed AWS-LC instead of vendor/aws-lc" OFF)
option(EMBERLYN_COVERAGE "Enable Cython line tracing for coverage" OFF)

if(EMBERLYN_SYSTEM_AWS_LC)
  find_package(aws-lc REQUIRED CONFIG)
  set(_tls_libraries AWS::ssl AWS::crypto)
  get_target_property(_tls_include AWS::crypto INTERFACE_INCLUDE_DIRECTORIES)
else()
  set(BUILD_TOOL OFF CACHE BOOL "" FORCE)
  set(BUILD_LIBSSL ON CACHE BOOL "" FORCE)
  set(DISABLE_GO ON CACHE BOOL "" FORCE)
  set(DISABLE_PERL ON CACHE BOOL "" FORCE)
  set(ENABLE_SOURCE_MODIFICATION OFF CACHE BOOL "" FORCE)
  # Visual Studio also generates Debug, whose default debug format is unknown
  # to the clang assembler of Windows Arm64; wheels ship no PDB files anyway.
  set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "")
  add_subdirectory(vendor/aws-lc EXCLUDE_FROM_ALL)
  set(_tls_libraries ssl crypto)
  set(_tls_include "${CMAKE_CURRENT_SOURCE_DIR}/vendor/aws-lc/include")
endif()

# ngtcp2 only probes the TLS headers for its AWS-LC macro; linking is ours.
set(ENABLE_LIB_ONLY ON CACHE BOOL "" FORCE)
set(ENABLE_SHARED_LIB OFF CACHE BOOL "" FORCE)
set(ENABLE_STATIC_LIB ON CACHE BOOL "" FORCE)
set(ENABLE_OPENSSL OFF CACHE BOOL "" FORCE)
set(ENABLE_GNUTLS OFF CACHE BOOL "" FORCE)
set(ENABLE_WOLFSSL OFF CACHE BOOL "" FORCE)
set(ENABLE_PICOTLS OFF CACHE BOOL "" FORCE)
set(ENABLE_BORINGSSL ON CACHE BOOL "" FORCE)
set(BORINGSSL_INCLUDE_DIR "${_tls_include}" CACHE PATH "" FORCE)
set(BORINGSSL_LIBRARIES "" CACHE STRING "" FORCE)
add_subdirectory(vendor/ngtcp2 EXCLUDE_FROM_ALL)
# nghttp3 reads the same ENABLE_*_LIB options set above. Both projects define
# a "check" target for their own test suites; keep ngtcp2's and drop the
# second, since neither runs here.
macro(add_custom_target name)
  if(NOT "${name}" STREQUAL "check" OR NOT TARGET check)
    _add_custom_target(${name} ${ARGN})
  endif()
endmacro()
add_subdirectory(vendor/nghttp3 EXCLUDE_FROM_ALL)

find_package(
  Python
  COMPONENTS Interpreter Development.Module
  REQUIRED)
find_package(Cython MODULE REQUIRED VERSION 3.1)
include(UseCython)

# Source paths in the generated C, which coverage follows to the .pxi files,
# stay relative to the project instead of the build directory.
set(_cython_args --working "${CMAKE_CURRENT_SOURCE_DIR}")
if(EMBERLYN_COVERAGE)
  list(APPEND _cython_args --directive linetrace=True)
endif()

# Target names are flat; the module path decides the file and its package.
set(_modules _core events h3/_core h3/events)
foreach(module IN LISTS _modules)
  string(REPLACE "/" "_" target "${module}")
  get_filename_component(name "${module}" NAME)
  get_filename_component(package "${SKBUILD_PROJECT_NAME}/${module}" DIRECTORY)
  cython_transpile(
    src/${SKBUILD_PROJECT_NAME}/${module}.pyx
    LANGUAGE C
    CYTHON_ARGS ${_cython_args}
    OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/${target}.c"
    OUTPUT_VARIABLE _source)
  python_add_library(${target} MODULE "${_source}" WITH_SOABI)
  set_target_properties(
    ${target} PROPERTIES OUTPUT_NAME ${name} LIBRARY_OUTPUT_DIRECTORY
                                             "${CMAKE_CURRENT_BINARY_DIR}/${package}")
  target_include_directories(${target} PRIVATE src/${SKBUILD_PROJECT_NAME}/includes)
  if(WIN32)
    # windows.h would pull in wincrypt.h, whose X509_NAME and other macros
    # collide with AWS-LC's declarations.
    target_compile_definitions(${target} PRIVATE WIN32_LEAN_AND_MEAN)
  endif()
  if(EMBERLYN_COVERAGE)
    # Coverage's Cython plugin needs the legacy tracing backend on Python 3.13+.
    target_compile_definitions(
      ${target} PRIVATE CYTHON_TRACE=1 CYTHON_USE_SYS_MONITORING=0)
  endif()
  install(TARGETS ${target} DESTINATION ${package})
endforeach()

# QUIC: the only module that links ngtcp2 and AWS-LC.
target_link_libraries(_core PRIVATE ngtcp2_crypto_boringssl_static ngtcp2_static
                                    ${_tls_libraries})
# HTTP/3 links only nghttp3. It reads ngtcp2 and AWS-LC headers for types and
# calls them through ngquic._core, so each library exists once per process.
target_link_libraries(h3__core PRIVATE nghttp3_static)
target_include_directories(
  h3__core
  PRIVATE $<TARGET_PROPERTY:ngtcp2_static,INTERFACE_INCLUDE_DIRECTORIES>
          $<TARGET_PROPERTY:ngtcp2_crypto_boringssl_static,INTERFACE_INCLUDE_DIRECTORIES>
          "${_tls_include}"
          # nghttp3's static target exports no build-tree include directories.
          vendor/nghttp3/lib/includes
          "${CMAKE_CURRENT_BINARY_DIR}/vendor/nghttp3/lib/includes")
# Export only the module init functions: CPython's _ssl and cryptography load
# their own OpenSSL into the same process.
foreach(target _core h3__core)
  if(APPLE)
    target_link_options(${target} PRIVATE "LINKER:-exported_symbol,_PyInit__core")
  elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_options(${target} PRIVATE "LINKER:--exclude-libs,ALL")
  endif()
endforeach()
