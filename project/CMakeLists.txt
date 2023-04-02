cmake_minimum_required (VERSION 3.10)

project (StudentContest CXX)

set (CMAKE_CXX_STANDARD 17)
set (CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable (${PROJECT_NAME})

target_include_directories (
    ${PROJECT_NAME}
    PRIVATE
        3rdparty/include
        include
)

file(GLOB THIRD_PARTY_LIBS 3rdparty/lib/*.a)
target_link_libraries (
    ${PROJECT_NAME}
    PRIVATE
        ${THIRD_PARTY_LIBS}
)

target_sources (
    ${PROJECT_NAME}
    PRIVATE
        src/main.cpp
)

