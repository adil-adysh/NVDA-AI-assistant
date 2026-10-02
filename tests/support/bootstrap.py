"""One supported import mechanism for add-on tests.

NVDA requires the on-disk add-on directory to be named ``AI-assistant``.  That
name cannot be used in a normal Python import statement, so tests load modules
under isolated, valid package names while executing the real production files.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADDON_ROOT = PROJECT_ROOT / "addon" / "globalPlugins" / "AI-assistant"
LIB_ROOT = ADDON_ROOT / "lib"
if str(LIB_ROOT) not in sys.path:
	sys.path.insert(0, str(LIB_ROOT))


def register_package(name: str, path: Path | None = None) -> ModuleType:
	"""Register an isolated package rooted at a real add-on directory."""
	package = types.ModuleType(name)
	if path is not None:
		package.__path__ = [str(path)]
	package.__package__ = name
	sys.modules[name] = package
	return package


def load_module(name: str, path: Path) -> ModuleType:
	"""Execute a real production module under an isolated test package name."""
	spec = importlib.util.spec_from_file_location(
		name,
		path,
		submodule_search_locations=[str(path.parent)] if path.name == "__init__.py" else None,
	)
	if spec is None or spec.loader is None:
		raise ImportError(f"Unable to load {name} from {path}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


def load_addon_module(dotted_name: str, *, namespace: str = "nvda_ai_assistant_tests") -> ModuleType:
	"""Load an add-on module without executing NVDA's global-plugin entry point."""
	parts = dotted_name.split(".")
	register_package(namespace, ADDON_ROOT)
	for index in range(1, len(parts)):
		package_name = ".".join((namespace, *parts[:index]))
		package_path = ADDON_ROOT.joinpath(*parts[:index])
		register_package(package_name, package_path)
	module_path = ADDON_ROOT.joinpath(*parts).with_suffix(".py")
	if not module_path.is_file():
		module_path = ADDON_ROOT.joinpath(*parts, "__init__.py")
	return load_module(".".join((namespace, *parts)), module_path)
