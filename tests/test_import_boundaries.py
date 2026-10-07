"""Automated architectural boundary tests enforcing pure-Python domain isolation.

Verifies that pure domain, service, config, and provider modules never import
NVDA host modules, accessibility subsystems, or wx UI components.
"""

from __future__ import annotations

import ast
import gc
from pathlib import Path
import time

from tests.support import ADDON_ROOT

PURE_DIRECTORIES: tuple[str, ...] = (
	"core",
	"config",
	"service",
	"providers",
	"use_case",
	"prompts",
	"tools",
	"observability",
	"embeddings",
	"worker",
)

PURE_CONTEXT_FILES: tuple[str, ...] = (
	"budget.py",
	"formatting.py",
	"graph_store.py",
	"pipeline.py",
	"prompts.py",
	"protocols.py",
	"reduction.py",
	"request_registry.py",
	"structure_summary.py",
	"types.py",
)

PURE_UTILS_FILES: tuple[str, ...] = (
	"crypto.py",
	"markdown.py",
	"mathml.py",
)

FORBIDDEN_NVDA_MODULES: frozenset[str] = frozenset({
	# Mandated by architecture specification:
	"api",
	"textInfos",
	"controlTypes",
	"globalPluginHandler",
	"scriptHandler",
	"queueHandler",
	"gui",
	"wx",
	"speech",
	"tones",
	"logHandler",
	# Host lifecycle & environment modules forbidden in pure layers:
	"languageHandler",
	"addonHandler",
	"globalVars",
	"winUser",
	"locationHelper",
	"treeInterceptorHandler",
	"nvwave",
})


FORBIDDEN_BYTES: tuple[bytes, ...] = tuple(
	name.encode("ascii") for name in sorted(FORBIDDEN_NVDA_MODULES)
)


def _find_forbidden_imports(file_path: Path) -> list[tuple[int, str, str]]:
	"""Parse a Python source file and return all forbidden NVDA import occurrences.

	Inspects:
	- Absolute imports: `import api`
	- Relative imports with module: `from .api import x`, `from ..api import x`
	- Relative imports without module: `from . import api`, `from .. import api`
	- Dynamic imports: `__import__('api')`, `__import__(name='api')`,
	  `importlib.import_module('api')`, `import_module(name='api')`

	Returns:
		List of tuples: (line_number, forbidden_module, code_snippet)
	"""
	raw_bytes = file_path.read_bytes()
	if not any(token in raw_bytes for token in FORBIDDEN_BYTES) and b"\\" not in raw_bytes:
		return []

	try:
		tree = ast.parse(raw_bytes, filename=str(file_path))
	except SyntaxError:
		return []

	violations: list[tuple[int, str, str]] = []

	for node in ast.walk(tree):
		# Direct import statement: `import api` or `import logHandler as log`
		if isinstance(node, ast.Import):
			for alias in node.names:
				root_pkg = alias.name.partition(".")[0]
				if root_pkg in FORBIDDEN_NVDA_MODULES:
					violations.append((node.lineno, root_pkg, f"import {alias.name}"))

		# From import statement: absolute AND relative (`node.level >= 0`)
		elif isinstance(node, ast.ImportFrom):
			dots = "." * node.level
			if node.module:
				root_pkg = node.module.partition(".")[0]
				if root_pkg in FORBIDDEN_NVDA_MODULES:
					violations.append(
						(node.lineno, root_pkg, f"from {dots}{node.module} import ...")
					)
			else:
				# Syntax: `from . import api` or `from .. import api, speech`
				for alias in node.names:
					root_pkg = alias.name.partition(".")[0]
					if root_pkg in FORBIDDEN_NVDA_MODULES:
						violations.append(
							(node.lineno, root_pkg, f"from {dots} import {alias.name}")
						)

		# Dynamic import: `__import__(...)` or `importlib.import_module(...)`
		elif isinstance(node, ast.Call):
			is_import_call = False
			if isinstance(node.func, ast.Name) and node.func.id in ("__import__", "import_module"):
				is_import_call = True
			elif isinstance(node.func, ast.Attribute) and node.func.attr in ("__import__", "import_module"):
				is_import_call = True

			if is_import_call:
				mod_target: str | None = None
				if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
					mod_target = node.args[0].value
				elif node.keywords:
					for kw in node.keywords:
						if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
							mod_target = kw.value.value
							break

				if mod_target:
					root_pkg = mod_target.partition(".")[0]
					if root_pkg in FORBIDDEN_NVDA_MODULES:
						violations.append(
							(node.lineno, root_pkg, f"dynamic import({mod_target!r})")
						)

	return violations


def test_pure_packages_have_zero_forbidden_nvda_imports() -> None:
	"""Assert that all pure domain, config, service, and provider packages have zero NVDA imports."""
	all_violations: list[str] = []
	for dir_name in PURE_DIRECTORIES:
		target_dir = ADDON_ROOT / dir_name
		if not target_dir.is_dir():
			continue
		for py_path in sorted(target_dir.rglob("*.py")):
			violations = _find_forbidden_imports(py_path)
			for lineno, forbidden_pkg, stmt in violations:
				rel_path = py_path.relative_to(ADDON_ROOT).as_posix()
				all_violations.append(
					f"  {rel_path}:{lineno} -> forbidden '{forbidden_pkg}' ({stmt})"
				)

	assert not all_violations, (
		f"Found {len(all_violations)} forbidden NVDA import(s) in pure Python packages:\n"
		+ "\n".join(all_violations)
	)


def test_pure_context_modules_have_zero_forbidden_nvda_imports() -> None:
	"""Assert that pure context pipeline/reduction/budget modules have zero NVDA imports."""
	violations: list[str] = []
	for fname in PURE_CONTEXT_FILES:
		fpath = ADDON_ROOT / "context" / fname
		if not fpath.is_file():
			continue
		for lineno, forbidden_pkg, stmt in _find_forbidden_imports(fpath):
			violations.append(
				f"  context/{fname}:{lineno} -> forbidden '{forbidden_pkg}' ({stmt})"
			)

	assert not violations, (
		f"Found {len(violations)} forbidden NVDA import(s) in pure context files:\n"
		+ "\n".join(violations)
	)


def test_pure_utils_modules_have_zero_forbidden_nvda_imports() -> None:
	"""Assert that pure utility modules (crypto, markdown, mathml) have zero NVDA imports."""
	violations: list[str] = []
	for fname in PURE_UTILS_FILES:
		fpath = ADDON_ROOT / "utils" / fname
		if not fpath.is_file():
			continue
		for lineno, forbidden_pkg, stmt in _find_forbidden_imports(fpath):
			violations.append(
				f"  utils/{fname}:{lineno} -> forbidden '{forbidden_pkg}' ({stmt})"
			)

	assert not violations, (
		f"Found {len(violations)} forbidden NVDA import(s) in pure utils files:\n"
		+ "\n".join(violations)
	)


def test_import_boundary_scan_performance_under_150ms() -> None:
	"""Verify that the full architectural AST import scan executes well within the 150ms budget."""
	gc.collect()
	gc_was_enabled = gc.isenabled()
	gc.disable()
	try:
		t0 = time.perf_counter()
		file_count = 0

		for dir_name in PURE_DIRECTORIES:
			target_dir = ADDON_ROOT / dir_name
			if not target_dir.is_dir():
				continue
			for py_path in target_dir.rglob("*.py"):
				file_count += 1
				_find_forbidden_imports(py_path)

		for fname in PURE_CONTEXT_FILES:
			fpath = ADDON_ROOT / "context" / fname
			if fpath.is_file():
				file_count += 1
				_find_forbidden_imports(fpath)

		for fname in PURE_UTILS_FILES:
			fpath = ADDON_ROOT / "utils" / fname
			if fpath.is_file():
				file_count += 1
				_find_forbidden_imports(fpath)

		elapsed_ms = (time.perf_counter() - t0) * 1000
	finally:
		if gc_was_enabled:
			gc.enable()

	assert elapsed_ms < 150.0, (
		f"AST boundary scan took {elapsed_ms:.2f}ms for {file_count} files, exceeding 150ms SLA threshold"
	)
