"""Tests for the autotools processor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.processors.autotools import AutotoolsProcessor


class TestAutotoolsProcessor:
    def setup_method(self):
        self.p = AutotoolsProcessor()

    def test_can_handle_autotools(self):
        for cmd in (
            "autoreconf -i",
            "autoreconf --install",
            "automake --add-missing",
            "autoconf",
            "libtoolize --force",
            "./configure --prefix=/usr",
            "./configure --enable-debug",
        ):
            assert self.p.can_handle(cmd), cmd
        assert not self.p.can_handle("make")
        assert not self.p.can_handle("./configure_with_typo --prefix")
        assert not self.p.can_handle("echo hello")

    def test_configure_collapses_routine_checks(self):
        output = "\n".join(
            [
                "configure: loading site script /usr/share/config.site",
                "checking for a BSD-compatible install... /usr/bin/install -c",
                "checking whether build environment is sane... yes",
                "checking for a thread-safe mkdir -p... /usr/bin/mkdir -p",
                "checking for gcc... gcc",
                "checking whether the C compiler works... yes",
                "checking for libffi... yes",
                "checking for libxml-2.0... no",
                "checking whether we are cross compiling... no",
                "checking that generated files are newer than configure... done",
                "configure: creating ./config.status",
            ]
        )
        result = self.p.process("./configure --prefix=/usr", output)
        assert "configure" in result
        assert "yes=" in result
        assert "no=" in result
        assert "libxml-2.0" in result
        # routine trait checks should not be shown verbatim
        assert "checking for gcc... gcc" not in result
        assert "checking whether we are cross compiling... no" not in result

    def test_autoreconf_traces_collapsed(self):
        output = "\n".join(
            [
                "autoreconf: Entering directory `.'",
                "autoreconf: configure.ac: tracing dependencies",
                "autoreconf: running: aclocal --force",
                "autoreconf: running: libtoolize --copy --force",
                "autoreconf: running: automake --add-missing --copy --force-missing",
                "autoreconf: running: autoconf --force",
                "autoreconf: Leaving directory `.'",
            ]
        )
        result = self.p.process("autoreconf -i", output)
        assert "traces" in result
        assert "autoreconf: Entering" not in result
