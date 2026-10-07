import pytest
import pathlib
import sys
import gettext
import builtins
import tempfile

PROJECT_ROOT = pathlib.Path.cwd()
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"

# Read original test_browser_field_parser.py
orig_parser_test = (PROJECT_ROOT / "tests" / "context" / "extractors" / "test_browser_field_parser.py").read_text(encoding="utf-8")

# Prepare modified test_browser_field_parser.py with:
# 1. import pytest
# 2. pytestmark = pytest.mark.nvda_integration
# 3. try/except around import controlTypes
modified_parser_test = orig_parser_test.replace(
    "import controlTypes\n\nfrom tests.support import ADDON_ROOT, load_module, register_package\n\n\nMODULE_PATH = ADDON_ROOT / \"context\" / \"extractors\" / \"browser_field_parser.py\"\n\n\nRole = controlTypes.Role",
    "import pytest\n\npytestmark = pytest.mark.nvda_integration\n\ntry:\n\timport controlTypes\n\tRole = controlTypes.Role\nexcept ImportError:\n\tcontrolTypes = None\n\tRole = None\n\nfrom tests.support import ADDON_ROOT, load_module, register_package\n\n\nMODULE_PATH = ADDON_ROOT / \"context\" / \"extractors\" / \"browser_field_parser.py\""
)

# Ensure PROJECT_ROOT is on sys.path
sys.path.insert(0, str(PROJECT_ROOT))

with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    target_test_file = d / "test_browser_field_parser.py"
    target_test_file.write_text(modified_parser_test, encoding="utf-8")

    # 1. Test with HAS_NVDA_CHECKOUT = False (simulated missing checkout)
    conftest_missing = f"""import pytest
import sys

sys.path.insert(0, r"{PROJECT_ROOT}")

HAS_NVDA_CHECKOUT = False

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

    # Run pytest on target_test_file with -m "not nvda_integration"
    print("\n=== Simulation: Checkout MISSING, -m 'not nvda_integration' ===")
    ret1 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), "-m", "not nvda_integration", str(target_test_file)])
    print("Return code:", ret1)

    print("\n=== Simulation: Checkout MISSING, direct run without -m ===")
    ret2 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), str(target_test_file)])
    print("Return code:", ret2)

    print("\n=== Simulation: Checkout MISSING, -m 'nvda_integration' ===")
    ret3 = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), "-m", "nvda_integration", str(target_test_file)])
    print("Return code:", ret3)
