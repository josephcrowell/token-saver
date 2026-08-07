"""Tests for the ADB processor."""

from src.processors.adb import AdbProcessor


class TestAdbProcessor:
    def setup_method(self):
        self.p = AdbProcessor()

    def test_can_handle_adb_subcommands(self):
        for cmd in (
            "adb install -r app.apk",
            "adb install -r -d build/app/outputs/flutter-apk/app-release.apk",
            "adb -s HGR282VP install -r -d build/app/outputs/flutter-apk/app.apk",
            "adb uninstall com.example",
            "adb -s HGR282VP uninstall au.com.annon.paper_delivery",
            "adb shell pm list packages -3",
            "adb shell pm uninstall --user 0 com.example",
            "adb shell monkey -p com.example -c android.intent.category.LAUNCHER 1",
            "adb logcat -d",
            "adb pull /sdcard/foo .",
            "adb push foo /sdcard/",
        ):
            assert self.p.can_handle(cmd), cmd
        assert not self.p.can_handle("echo hello")
        assert not self.p.can_handle("flutter build apk")

    def test_pm_list_packages_keeps_sample(self):
        output = "\n".join(f"package:au.com.example{i}" for i in range(50))
        result = self.p.process("adb shell pm list packages -3", output)
        assert "50 packages" in result
        assert "au.com.example0" in result
        assert "au.com.example49" in result
        assert "au.com.example25" not in result
        assert "..." in result

    def test_logcat_preserves_fatal_block(self):
        lines = []
        for i in range(500):
            lines.append(f"01-15 10:23:0{i%10}.000  1000  1000 I SystemServer: heartbeat {i}")
        # Inject a fatal block near the end
        lines.append("01-15 10:23:50.000  1234  1234 E AndroidRuntime: FATAL EXCEPTION: main")
        lines.append(
            "01-15 10:23:50.001  1234  1234 E AndroidRuntime: java.lang.NullPointerException"
        )
        lines.append(
            "01-15 10:23:50.002  1234  1234 E AndroidRuntime: "
            "at com.example.Foo.bar(Foo.java:42)"
        )
        output = "\n".join(lines)
        result = self.p.process("adb logcat -d", output)
        assert "FATAL EXCEPTION" in result
        assert "NullPointerException" in result
        assert "lines" in result
        # The big chunk of routine heartbeat lines should be collapsed
        assert "heartbeat 100" not in result

    def test_install_keeps_status_strips_progress(self):
        output = "\n".join(
            [
                "Performing Streamed Install",
                "  [   1%] /data/local/tmp/app-debug.apk",
                "  [  50%] /data/local/tmp/app-debug.apk",
                "  [ 100%] /data/local/tmp/app-debug.apk",
                "Success",
            ]
        )
        result = self.p.process("adb install -r app.apk", output)
        assert "Performing Streamed Install" in result
        assert "Success" in result
        assert "[  50%]" not in result

    def test_uninstall_summary(self):
        output = "Success\n"
        result = self.p.process("adb uninstall com.example", output)
        assert "Uninstall OK" in result

    def test_uninstall_failure_passes_through(self):
        output = "Failure [DELETE_FAILED_INTERNAL_ERROR]\n"
        result = self.p.process("adb uninstall com.example", output)
        assert "Failure" in result
        assert "DELETE_FAILED" in result
