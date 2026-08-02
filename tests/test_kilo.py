"""Tests for Kilo Code installation assets."""

import os
import shutil
import tempfile
from unittest import mock


class TestKiloInstaller:
    def setup_method(self):
        self.tmp_home = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.tmp_home, "kilo-config")
        self.core_dir = os.path.join(self.tmp_home, "core")
        self.bridge = os.path.join(self.core_dir, "kilo", "compress.py")

    def teardown_method(self):
        shutil.rmtree(self.tmp_home, ignore_errors=True)

    def test_install_writes_native_plugin_skill_and_command(self):
        from installers import kilo

        with (
            mock.patch.dict(os.environ, {"KILO_CONFIG_DIR": self.config_dir}),
            mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir),
        ):
            kilo.install(use_symlink=False)

        plugin_path = os.path.join(self.config_dir, "plugins", "token-saver.js")
        with open(plugin_path) as f:
            plugin = f.read()
        assert '"tool.execute.after"' in plugin
        assert self.bridge in plugin
        assert os.path.isfile(
            os.path.join(self.config_dir, "skills", "token-saver-config", "SKILL.md")
        )
        assert os.path.isfile(
            os.path.join(self.config_dir, "skills", "token-saver-graphify", "SKILL.md")
        )
        assert os.path.isfile(
            os.path.join(self.config_dir, "commands", "token-saver-stats.md")
        )

    def test_uninstall_only_removes_token_saver_assets(self):
        from installers import kilo

        unrelated = os.path.join(self.config_dir, "plugins", "other.js")
        os.makedirs(os.path.dirname(unrelated), exist_ok=True)
        with open(unrelated, "w") as f:
            f.write("export {}")

        with (
            mock.patch.dict(os.environ, {"KILO_CONFIG_DIR": self.config_dir}),
            mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir),
        ):
            kilo.install(use_symlink=False)
            kilo.uninstall()

        assert os.path.isfile(unrelated)
        assert not os.path.exists(os.path.join(self.config_dir, "plugins", "token-saver.js"))
        assert not os.path.exists(
            os.path.join(self.config_dir, "commands", "token-saver-stats.md")
        )
        assert not os.path.exists(
            os.path.join(self.config_dir, "skills", "token-saver-graphify", "SKILL.md")
        )

    def test_rendered_plugin_handles_bash_case_insensitively(self):
        from installers.kilo import _render_plugin

        with mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir):
            plugin = _render_plugin()
        assert 'String(input.tool || "").toLowerCase()' in plugin
        assert 'output.output = result.output' in plugin
        assert '"tool.execute.before"' in plugin
        assert "compressGraphify" in plugin
        assert "graphify_metrics.py" in plugin

    def test_plugin_never_references_source_checkout(self):
        from installers import kilo

        with (
            mock.patch.dict(os.environ, {"KILO_CONFIG_DIR": self.config_dir}),
            mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir),
        ):
            kilo.install(use_symlink=False)

        plugin_path = os.path.join(self.config_dir, "plugins", "token-saver.js")
        with open(plugin_path) as f:
            plugin = f.read()
        assert self.bridge in plugin
        assert kilo.__file__ not in plugin
