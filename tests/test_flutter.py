"""Tests for Flutter / Dart processor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.processors.flutter import FlutterProcessor


class TestFlutterProcessor:
    def setup_method(self):
        self.p = FlutterProcessor()

    def test_can_handle_flutter_and_dart(self):
        for cmd in (
            "flutter build apk --debug",
            "flutter test",
            "flutter pub get",
            "flutter pub deps",
            "flutter analyze",
            "flutter doctor -v",
            "flutter run -d HGR282VP",
            "/home/joseph/flutter/bin/flutter build apk",
            "dart run",
            "dart analyze",
            "dart pub get",
        ):
            assert self.p.can_handle(cmd), cmd
        assert not self.p.can_handle("echo hello")
        assert not self.p.can_handle("cd build && ninja")

    def test_compresses_flutter_build_progress(self):
        output = "\n".join(
            [
                "Resolving dependencies...",
                "Got dependencies!",
                "Downloading package_assets 1.0.0",
                "Downloading grdk_plugins 2.0.0",
                "Downloading some_tool 1.2.0",
                "  /root/.pub-cache/hosted/pub.dev/grdk-2.0.0",
                "  /root/.pub-cache/hosted/pub.dev/grdk_plugins-2.0.0",
                "Built build/ios/iphonesimulator/Runner.app.",
                "✓ Built build/app/outputs/flutter-apk/app-debug.apk",
                "[1/5] Reading build settings for target",
                "[2/5] Copying Cxx source files",
                "[3/5] Creating modulemap",
                "[4/5] Compiling with swiftc",
                "[5/5] Linking",
                "Running Gradle task 'assembleRelease'...",
                "Running Xcode build...",
                "FAILURE: Build failed with an exception.",
                "* Where:",
                "File 'lib/main.dart':12:5",
                "lib/main.dart",
            ]
        )
        result = self.p.process("flutter build apk", output)
        assert "FAILURE" in result
        assert "lib/main.dart" in result
        assert "Downloading package_assets" not in result
        assert "[1/5] Reading build settings" not in result
        assert "Built build/ios/iphonesimulator" not in result
        assert "progress lines stripped" in result

    def test_flutter_doctor_summary(self):
        output = "\n".join(
            [
                "Doctor summary (to see all details, run flutter doctor -v):",
                "[✓] Flutter (Channel stable, 3.44.0)",
                "[✓] Android toolchain - develop for Android devices",
                "[✗] Android Studio",
                "    ✗ Unable to find bundled Java version.",
                "[!] Connected device",
                "    ! No devices available.",
            ]
        )
        result = self.p.process("flutter doctor -v", output)
        assert "Flutter doctor" in result
        assert "2 ok" in result
        assert "1 problems" in result or "2 problems" in result
        assert "bundled Java" in result

    def test_flutter_pub_deps_collapses_tree(self):
        output = "\n".join(
            [
                "Dart SDK 3.4.0",
                "Flutter SDK 3.44.0",
                "my_app 1.0.0+1",
                "├── flutter 3.44.0",
                "│   ├── meta 1.0.0",
                "│   └── collection 1.18.0",
                "├── http 1.0.0",
                "│   └── http_parser 4.0.2",
                "├── json_annotation 4.9.0",
                "├── path 1.9.0",
                "├── flutter_test 0.0.0",
                "└── provider 6.0.0",
            ]
        )
        result = self.p.process("flutter pub deps", output)
        assert "pub deps" in result
        assert "Top-level" in result
        assert "provider" in result

    def test_flutter_analyze_groups_findings(self):
        output = "\n".join(
            [
                "Analyzing my_app...",
                "",
                "  error - Undefined class 'Foo' at lib/main.dart:5:1",
                "  warning - Avoid using `print` in production code at lib/main.dart:10:1",
                "  info - Use `const` literals at lib/widgets.dart:3:1",
                "",
                "1 issue found.",
            ]
        )
        result = self.p.process("flutter analyze", output)
        assert "1 errors" in result
        assert "lib/main.dart:5" in result
        assert "1 issue found" in result
