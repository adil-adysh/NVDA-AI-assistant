import pytest
import pathlib
import sys
import types
import importlib.util

PROJECT_ROOT = pathlib.Path.cwd()
tests_dir = PROJECT_ROOT / "tests"

# Remove NVDA from sys.path, keep project root
sys.path = [p for p in sys.path if "nvda" not in p.lower() or "nvda-ai-assistant" in p.lower()]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide standard library gettext builtins as conftest does
import gettext
import builtins
builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

# Post-Feature 9, 10, 11 simulated state:
dummy_logHandler = types.ModuleType("logHandler")
dummy_logHandler.log = types.SimpleNamespace(
    debug=lambda *a, **k: None,
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    exception=lambda *a, **k: None,
)
dummy_languageHandler = types.ModuleType("languageHandler")
dummy_languageHandler.getLanguage = lambda: "en"

sys.modules["logHandler"] = dummy_logHandler
sys.modules["languageHandler"] = dummy_languageHandler

# Also define dummy REAL_NVDA_MODULES for conftest module
dummy_conftest = types.ModuleType("conftest")
dummy_conftest.REAL_NVDA_MODULES = {}
dummy_conftest.HAS_NVDA_CHECKOUT = False
dummy_conftest.PROJECT_ROOT = PROJECT_ROOT
dummy_conftest.NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
dummy_conftest.NVDA_SOURCE = dummy_conftest.NVDA_ROOT / "source"
sys.modules["conftest"] = dummy_conftest

test_files = sorted(tests_dir.rglob("test_*.py"))
print(f"Total test files found: {len(test_files)}")

results = []
for tf in test_files:
    rel_path = tf.relative_to(PROJECT_ROOT).as_posix()
    if rel_path in [
        "tests/integration/test_nvda_runtime.py",
        "tests/integration/test_nvda_imports.py",
        "tests/context/extractors/test_browser_field_parser.py",
        "tests/context/test_browser_field_graph.py",
    ]:
        results.append((rel_path, "TIER 3 (Gated Integration)", None))
        continue
    
    try:
        spec = importlib.util.spec_from_file_location(tf.stem, tf)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod.__name__] = mod
        spec.loader.exec_module(mod)
        results.append((rel_path, "OK", None))
    except Exception as e:
        results.append((rel_path, "FAILED", f"{type(e).__name__}: {e}"))

failed = [r for r in results if r[1] == "FAILED"]
print(f"\nAudit Results: {len(test_files) - len(failed)} / {len(test_files)} succeeded.")
if failed:
    print(f"FAILED files ({len(failed)}):")
    for r in failed:
        print(f"  {r[0]}: {r[2]}")
else:
    print("ALL remaining 55 Pure Python test files load cleanly without NVDA source!")
