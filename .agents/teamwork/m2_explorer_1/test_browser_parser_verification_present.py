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

nvda_source_str = str(NVDA_SOURCE).replace("\\", "\\\\")
nvda_misc_deps_str = str(NVDA_ROOT / "miscDeps" / "python").replace("\\", "\\\\")
project_root_str = str(PROJECT_ROOT).replace("\\", "\\\\")

with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    target_test_file = d / "test_browser_field_parser.py"
    target_test_file.write_text(modified_parser_test, encoding="utf-8")

    conftest_present = f"""import pytest
import sys
import builtins
import gettext
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(r"{project_root_str}")
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"
NVDA_MISC_DEPS = NVDA_ROOT / "miscDeps" / "python"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

for p in reversed((NVDA_SOURCE, NVDA_MISC_DEPS)):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

import globalVars
globalVars.appDir = str(NVDA_SOURCE)
globalVars.appArgs.disableAddons = True
cfg = Path(tempfile.gettempdir()) / "nvda-ai-assistant-tests"
cfg.mkdir(parents=True, exist_ok=True)
globalVars.appArgs.configPath = str(cfg)

import controlTypes
import logHandler
import textInfos

HAS_NVDA_CHECKOUT = True

def pytest_collection_modifyitems(config, items):
    if not HAS_NVDA_CHECKOUT:
        skip_marker = pytest.mark.skip(
            reason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."
        )
        for item in items:
            if "nvda_integration" in item.keywords:
                item.add_marker(skip_marker)
"""
    (d / "conftest.py").write_text(conftest_present, encoding="utf-8")

    print("\n=== Simulation: Checkout PRESENT, -m 'nvda_integration' ===")
    ret = pytest.main(["-c", str(PROJECT_ROOT / "pyproject.toml"), "-m", "nvda_integration", str(target_test_file)])
    print("Return code:", ret)
