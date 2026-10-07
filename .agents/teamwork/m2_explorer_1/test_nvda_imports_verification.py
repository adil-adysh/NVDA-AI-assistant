import pytest
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path.cwd()
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"

# Read original test_nvda_imports.py
orig_test = (PROJECT_ROOT / "tests" / "integration" / "test_nvda_imports.py").read_text(encoding="utf-8")

# Insert pytest and pytestmark correctly after from __future__ import annotations
modified_test = orig_test.replace(
    "from pathlib import Path\n\nfrom conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES",
    "from pathlib import Path\n\nimport pytest\n\nfrom conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES\n\n\npytestmark = pytest.mark.nvda_integration"
)

with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    target_test_file = d / "test_nvda_imports.py"
    target_test_file.write_text(modified_test, encoding="utf-8")

    # 1. Test with HAS_NVDA_CHECKOUT = False
    conftest_missing = f"""import pytest
from pathlib import Path
import sys

sys.path.insert(0, r"{PROJECT_ROOT}")

PROJECT_ROOT = Path(r"{PROJECT_ROOT}")
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"

HAS_NVDA_CHECKOUT = False
REAL_NVDA_MODULES = {{}}

def pytest_collection_modifyitems(config, items):
    if not HAS_NVDA_CHECKOUT:
        skip_marker = pytest.mark.skip(
            reason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."
        )
        for item in items:
            if "nvda_integration" in item.keywords:
                item.add_marker(skip_marker)
"""
    (d / "conftest.py").write_text(conftest_missing, encoding="utf-8")

    print("\n=== Simulation: Checkout MISSING, -m 'not nvda_integration' ===")
    ret1 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), "-m", "not nvda_integration", str(target_test_file)])
    print("Return code:", ret1)

    print("\n=== Simulation: Checkout MISSING, -m 'nvda_integration' ===")
    ret2 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), "-m", "nvda_integration", str(target_test_file)])
    print("Return code:", ret2)

    print("\n=== Simulation: Checkout MISSING, direct run without -m ===")
    ret3 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), str(target_test_file)])
    print("Return code:", ret3)
