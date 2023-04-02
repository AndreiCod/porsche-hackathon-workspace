set (CMAKE_SYSTEM_NAME Linux)
set (CMAKE_SYSTEM_VERSION 1)

set (TOOLCHAIN_PATH ${CMAKE_CURRENT_LIST_DIR})
set (ROOTFS_PATH "${TOOLCHAIN_PATH}/rootfs")
set (ENV{PATH} "${TOOLCHAIN_PATH}/bin;$ENV{PATH}")

SET (CMAKE_C_COMPILER   aarch64-none-linux-gnu-gcc)
SET (CMAKE_CXX_COMPILER aarch64-none-linux-gnu-g++)

# Where is the target environment
set (CMAKE_FIND_ROOT_PATH ${ROOTFS_PATH})

set (ENV{PKG_CONFIG_PATH} ${ROOTFS_PATH}/usr/lib/aarch64-linux-gnu/pkgconfig)

set (CMAKE_EXE_LINKER_FLAGS    "${CMAKE_EXE_LINKER_FLAGS}    --sysroot=${CMAKE_FIND_ROOT_PATH}")
set (CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} --sysroot=${CMAKE_FIND_ROOT_PATH}")
set (CMAKE_MODULE_LINKER_FLAGS "${CMAKE_MODULE_LINKER_FLAGS} --sysroot=${CMAKE_FIND_ROOT_PATH}")

# Search for programs only in the build host directories
set (CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)

# Search for libraries and headers only in the target directories
set (CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set (CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
