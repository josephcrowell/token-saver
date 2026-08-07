"""Tests for the iOS / macOS toolchain processor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.processors.ios_toolchain import IOSToolchainProcessor


class TestIOSToolchainProcessor:
    def setup_method(self):
        self.p = IOSToolchainProcessor()

    def test_can_handle_ios_commands(self):
        for cmd in (
            "pod install --repo-update",
            "pod update",
            "pod repo update",
            "pod deintegrate",
            "fastlane ios build",
            "fastlane beta",
            "bundle exec fastlane ios deploy",
            "xcodebuild -workspace Runner.xcworkspace -scheme Runner",
            "swift build",
            "swift test",
            "swift package resolve",
            "swift package update",
            "swift package show-dependencies",
        ):
            assert self.p.can_handle(cmd), cmd
        assert not self.p.can_handle("echo hello")
        assert not self.p.can_handle("flutter build apk")

    def test_pod_install_keeps_summary(self):
        output = "\n".join(
            [
                "Analyzing dependencies",
                "Downloading dependencies",
                "Installing Flutter (1.0.0)",
                "Installing SDWebImage (5.18.0)",
                "Installing GoogleMaps (8.0.0)",
                "  - Running pre install hooks",
                "Downloading -> GoogleMaps 8.0.0 (5.3 MB of 25.6 MB)",
                "Installing GoogleMaps 8.0.0 (5.3 MB of 25.6 MB)",
                "Pod installation complete!",
                "  - Integrating the Client",
            ]
        )
        result = self.p.process("pod install", output)
        assert "Pod" in result
        assert "Pod installation complete!" in result
        assert "Running pre install hooks" not in result

    def test_pod_install_error_preserved(self):
        output = "\n".join(
            [
                "Analyzing dependencies",
                "Downloading dependencies",
                "Installing Flutter (1.0.0)",
                "Pod installation complete!",
                "[!] Unable to find a target named `Runner`",
                "    Did you mean `Run`?",
            ]
        )
        result = self.p.process("pod install", output)
        assert "Unable to find a target" in result
        assert "Did you mean" in result

    def test_fastlane_summarizes_actions(self):
        output = "\n".join(
            [
                "[13:23:00]: --- Step: match",
                "[13:23:02]: All required keys are present in the keychain",
                "[13:23:03]: Successfully installed certificate",
                "[13:23:04]: Successfully installed provisioning profile",
                "[13:23:05]: --- Step: build_app",
                "[13:23:30]: ▸ Building project",
                "[13:23:32]: ▸ Touching build/Release-iphoneos/Runner.app",
                "[13:25:00]: fastlane.tools finished successfully 🎉",
            ]
        )
        result = self.p.process("fastlane ios beta", output)
        assert "Fastlane actions" in result
        assert "build_app" in result
        assert "Building project" in result

    def test_swift_build_collapses_progress(self):
        output = "\n".join(
            [
                "Computing version graph",
                "Fetching FromBase64.swift",
                "Resolving Package Graph",
                "Cloning Some/Package",
                "Checking out Some/Package 1.0.0",
                "Compiling MyPackage main.swift",
                "Compiling MyPackage helper.swift",
                "Compiling MyPackage utils.swift",
                "Linking MyPackage",
                "Build complete!",
            ]
        )
        result = self.p.process("swift build", output)
        assert "Build complete!" in result
        assert "Compiling MyPackage main" not in result
        assert "events" in result

    def test_swift_test_summarizes(self):
        output = "\n".join(
            [
                "Test Suite 'All tests' started at ...",
                "Test Suite 'MyTests' started",
                "Test Suite 'testFoo' passed at ...",
                "Test Suite 'testBar' passed at ...",
                "Test Suite 'testBaz' passed at ...",
                "Test Suite 'MyTests' passed at ...",
                "Test Suite 'All tests' passed at ...",
                "Executed 3 tests, with 0 failures",
            ]
        )
        result = self.p.process("swift test", output)
        assert "Tests:" in result
        assert "passed" in result
        assert "testFoo" in result

    def test_xcodebuild_keeps_errors(self):
        output = "\n".join(
            [
                "CompileC build/Release/main.o main.swift",
                "CompileC build/Release/helper.o helper.swift",
                "Ld build/Release-iphoneos/Runner.app/Runner",
                "/path/to/Runner/main.swift:42:5: error: use of unresolved identifier 'foo'",
                "/path/to/Runner/main.swift:43:5: warning: unused variable 'bar'",
                "** BUILD FAILED **",
            ]
        )
        result = self.p.process("xcodebuild -workspace Runner.xcworkspace -scheme Runner", output)
        assert "BUILD FAILED" in result
        assert "unresolved identifier 'foo'" in result
        assert "CompileC" not in result
