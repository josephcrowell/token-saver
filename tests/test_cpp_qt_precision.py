"""Precision tests for C/C++ and Qt processors."""

from src.engine import CompressionEngine


class TestCppQtPrecision:
    def setup_method(self):
        self.engine = CompressionEngine()

    def test_clang_template_diagnostic_chain_survives(self):
        output = "\n".join(
            [f"[{i}/200] Building CXX object generated/noise{i}.cpp.o" for i in range(1, 190)]
            + [
                "FAILED: src/model.cpp.o",
                "clang++ -std=c++20 -c src/model.cpp",
                "In file included from src/model.cpp:2:",
                "include/model.h:73:18: error: no matching function for call to 'visit'",
                "   73 |     return std::visit(visitor, value);",
                "      |            ~~~~~~~~~~^~~~~~~~~~~~~~~~",
                "include/visitor.h:41:9: note: candidate template ignored: substitution failure",
                "src/model.cpp:88:5: note: in instantiation of function template specialization",
                "ninja: build stopped: subcommand failed.",
            ]
        )
        compressed, processor, was_compressed = self.engine.compress("ninja -C build", output)
        assert was_compressed
        assert processor == "cpp_build"
        for signal in (
            "include/model.h:73:18",
            "no matching function",
            "std::visit(visitor, value)",
            "candidate template ignored",
            "instantiation of function template specialization",
            "ninja: build stopped",
        ):
            assert signal in compressed

    def test_linker_symbols_survive(self):
        output = "\n".join(
            [f"[{i}/100] Building CXX object src/file{i}.cpp.o" for i in range(1, 95)]
            + [
                "FAILED: app",
                "clang++ objects... -o app",
                "ld.lld: error: undefined symbol: vtable for MainWindow",
                ">>> referenced by mainwindow.cpp:22",
                ">>>               mainwindow.cpp.o:(MainWindow::MainWindow())",
                "ld.lld: error: duplicate symbol: App::instance()",
                ">>> defined at app.cpp:17",
                ">>> defined at app_test.cpp:9",
                "clang++: error: linker command failed with exit code 1",
            ]
        )
        compressed, _, _ = self.engine.compress("cmake --build build", output)
        assert "vtable for MainWindow" in compressed
        assert "mainwindow.cpp:22" in compressed
        assert "App::instance()" in compressed
        assert "app_test.cpp:9" in compressed
        assert "linker command failed" in compressed

    def test_qml_diagnostics_preserve_file_location_and_rule(self):
        output = "\n".join(
            [
                f"qml/Page{i}.qml:10:5: warning: Unqualified access [unqualified]"
                for i in range(30)
            ]
            + [
                "qml/Main.qml:21:9: error: Type Widget unavailable [import]",
                "qml/Widget.qml:4:1: error: module \"Missing.Module\" is not installed [import]",
            ]
        )
        compressed, processor, was_compressed = self.engine.compress("qmllint qml", output)
        assert was_compressed
        assert processor == "cpp_analysis"
        assert "qml/Main.qml:21:9" in compressed
        assert "Type Widget unavailable" in compressed
        assert "qml/Widget.qml:4:1" in compressed
        assert 'module \"Missing.Module\" is not installed' in compressed
        assert "unqualified: 30" in compressed

    def test_qttest_multiple_failures_survive(self):
        output = "\n".join(
            [f"PASS   : WidgetTest::passing(row{i})" for i in range(120)]
            + [
                "FAIL!  : WidgetTest::geometry(narrow) Compared values are not the same",
                "   Actual   (width): 9",
                "   Expected (10)   : 10",
                "   Loc: [tests/tst_widget.cpp(88)]",
                "FAIL!  : WidgetTest::signalDelivery(disconnected) Signal spy count mismatch",
                "   Actual   (spy.count()): 0",
                "   Expected (1)          : 1",
                "   Loc: [tests/tst_widget.cpp(121)]",
                "Totals: 120 passed, 2 failed, 0 skipped, 0 blacklisted, 20ms",
            ]
        )
        compressed, processor, was_compressed = self.engine.compress(
            "./tst_widget -o -,txt", output
        )
        assert was_compressed
        assert processor == "cpp_test"
        assert "geometry(narrow)" in compressed
        assert "width): 9" in compressed
        assert "tst_widget.cpp(88)" in compressed
        assert "signalDelivery(disconnected)" in compressed
        assert "spy.count()): 0" in compressed
        assert "tst_widget.cpp(121)" in compressed
        assert "120 passed, 2 failed" in compressed
