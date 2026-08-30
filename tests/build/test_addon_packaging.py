"""Packaging invariants for the distributable NVDA add-on archive."""

from __future__ import annotations

import zipfile
from pathlib import Path

from tests.support import PROJECT_ROOT, load_module


addon_tool = load_module(
	"addon_packaging_test_tool",
	PROJECT_ROOT / "site_scons" / "site_tools" / "NVDATool" / "addon.py",
)


def test_bundle_writer_never_packages_test_artifacts(tmp_path: Path) -> None:
	source = tmp_path / "addon"
	files = {
		"manifest.ini": "name = example\n",
		"globalPlugins/example/plugin.py": "SAFE = True\n",
		"globalPlugins/example/contest.py": "SAFE = True\n",
		"globalPlugins/example/test_plugin.py": "assert False\n",
		"globalPlugins/example/plugin_test.py": "assert False\n",
		"globalPlugins/example/conftest.py": "assert False\n",
		"globalPlugins/example/tests/helpers.py": "assert False\n",
		"globalPlugins/example/test/helpers.py": "assert False\n",
		"globalPlugins/example/__pycache__/plugin.pyc": "not bytecode",
		"globalPlugins/example/lib/markdown/test_tools.py": "assert False\n",
	}
	for relative_path, content in files.items():
		path = source / relative_path
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content, encoding="utf-8")

	destination = tmp_path / "example.nvda-addon"
	addon_tool.createAddonBundleFromPath(source, str(destination), excludePatterns=())

	with zipfile.ZipFile(destination) as archive:
		members = set(archive.namelist())

	assert members == {
		"manifest.ini",
		"globalPlugins/example/plugin.py",
		"globalPlugins/example/contest.py",
	}
