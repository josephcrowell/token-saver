"""Tests for the CMake configure processor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.processors.cmake_configure import CmakeConfigureProcessor


class TestCmakeConfigureProcessor:
    def setup_method(self):
        self.p = CmakeConfigureProcessor()

    def test_can_handle_cmake_configure(self):
        for cmd in (
            "cmake -B build -S .",
            "cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug",
            "cmake -G Ninja -B build",
            "cmake -DCMAKE_BUILD_TYPE=Debug -DCMAKE_PREFIX_PATH=/usr",
            "./configure --prefix=/usr",  # must NOT match cmake_configure
        ):
            if "configure" in cmd and "cmake" not in cmd:
                assert not self.p.can_handle(cmd), cmd
            else:
                assert self.p.can_handle(cmd), cmd
        assert not self.p.can_handle("cmake --build build")
        assert not self.p.can_handle("cmake --install build")
        assert not self.p.can_handle("cmake -E capabilities")
        assert not self.p.can_handle("cmake ..")
        assert not self.p.can_handle("echo hello")

    def test_configure_summarizes_checks(self):
        output = "\n".join(
            [
                "-- The C compiler identification is GNU 14.2.1",
                "-- The CXX compiler identification is GNU 14.2.1",
                "-- Detecting C/C++ compiler ABI info",
                "-- Detecting C compile features",
                "-- Performing Test CMAKE_HAVE_LIBC_PTHREAD",
                "-- Performing Test CMAKE_HAVE_LIBC_PTHREAD - Success",
                (
                    "-- Found PkgConfig: /usr/bin/pkg-config "
                    '(found suitable version "1.8.1", minimum required is "0.9.0")'
                ),
                "-- Checking for module 'systemd'",
                "--   Package 'systemd' not found",
                "-- Checking for module 'libffi'",
                "--   Found libffi, version 3.4.4",
                "-- Configuring done",
                "-- Generating done",
                "-- Build files have been written to: /home/joseph/Project/build",
            ]
        )
        result = self.p.process("cmake -B build -S .", output)
        assert "CMake configure" in result
        assert "Package 'systemd' not found" in result
        assert "Build files have been written" in result
        assert "Detecting C/C++ compiler ABI" not in result
        assert "Detecting C compile features" not in result

    def test_configure_passes_errors_through(self):
        output = "\n".join(
            [
                "-- The C compiler identification is GNU 14.2.1",
                "CMake Error at CMakeLists.txt:42 (find_package):",
                "  Could not find a package configuration file provided by \"Qt6\"",
                "-- Configuring incomplete, errors occurred!",
            ]
        )
        result = self.p.process("cmake -B build -S .", output)
        assert "CMake Error" in result
        assert "Could not find a package configuration" in result
        assert "incomplete" in result or "errors" in result
