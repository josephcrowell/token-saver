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

    def test_plugin_uses_kilo_default_export_shape(self):
        from installers import kilo

        with mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir):
            plugin = kilo._render_plugin()
        # Kilo Code's plugin loader requires `export default { id, server }`.
        # Without this, the plugin file is loaded but hooks never fire.
        assert "export default { id: \"token-saver\", server: TokenSaver }" in plugin
        assert "export const TokenSaver" not in plugin
        assert "BASH_TOOLS" in plugin
        assert "\"tool.execute.before\"" in plugin
        assert "\"tool.execute.after\"" in plugin

    def test_plugin_loads_in_node_runtime(self):
        import subprocess
        import tempfile

        from installers import kilo

        with mock.patch("installers.kilo.token_saver_data_dir", return_value=self.core_dir):
            plugin = kilo._render_plugin()
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(plugin)
            plugin_path = f.name
        try:
            node_bin = shutil.which("node") or "node"
            result = subprocess.run(  # noqa: S603
                [
                    node_bin,
                    "--input-type=module",
                    "-e",
                    (
                        "import('" + plugin_path + "').then(m => {"
                        "console.log('id=' + m.default.id);"
                        "console.log('has_server=' + (typeof m.default.server === 'function'));"
                        "m.default.server().then(h => {"
                        "console.log('hooks=' + Object.keys(h).join(','));"
                        "});"
                        "})"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert "id=token-saver" in result.stdout
            assert "has_server=true" in result.stdout
            assert "tool.execute.before" in result.stdout
            assert "tool.execute.after" in result.stdout
        finally:
            os.unlink(plugin_path)
