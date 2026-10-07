import pytest
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path.cwd()
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"

conftest_code_template = """\"\"\"Shared pytest bootstrap supporting both standalone pure-Python tests and NVDA integration.\"\"\"

from __future__ import annotations

import builtins
import gettext
import os
import subprocess
import sys
import tempfile
import tomllib
import warnings
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"
NVDA_MISC_DEPS = NVDA_ROOT / "miscDeps" / "python"
NVDA_VENV_SITE_PACKAGES = NVDA_ROOT / ".venv" / "Lib" / "site-packages"

HAS_NVDA_CHECKOUT = {has_nvda_checkout}

# Standard library translation functions installed unconditionally
builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

REAL_NVDA_MODULES: dict[str, object] = {{}}

if HAS_NVDA_CHECKOUT:
\twith (PROJECT_ROOT / "nvda-source.toml").open("rb") as pin_file:
\t\tNVDA_REVISION = tomllib.load(pin_file)["nvda"]["revision"]

\ttry:
\t\trevision = subprocess.run(
\t\t\t["git", "rev-parse", "HEAD"],
\t\t\tcwd=NVDA_ROOT,
\t\t\tcheck=True,
\t\t\tcapture_output=True,
\t\t\ttext=True,
\t\t).stdout.strip()
\t\tif revision != NVDA_REVISION:
\t\t\tmessage = (
\t\t\t\tf"Sibling NVDA checkout is at {{revision}}, but this project is tested against "
\t\t\t\tf"{{NVDA_REVISION}}. Run: git -C ../nvda checkout {{NVDA_REVISION}}"
\t\t\t)
\t\t\tif os.environ.get("CI"):
\t\t\t\traise pytest.UsageError(message)
\t\t\twarnings.warn(message, stacklevel=1)
\texcept Exception as e:
\t\tif os.environ.get("CI"):
\t\t\traise
\t\twarnings.warn(f"Could not verify sibling NVDA revision: {{e}}", stacklevel=1)

\tfor path in reversed((NVDA_SOURCE, NVDA_MISC_DEPS)):
\t\tpath_string = str(path)
\t\tif path_string not in sys.path:
\t\t\tsys.path.insert(0, path_string)

\tif NVDA_VENV_SITE_PACKAGES.is_dir():
\t\tsys.path.append(str(NVDA_VENV_SITE_PACKAGES))

\timport globalVars  # noqa: E402

\tglobalVars.appDir = str(NVDA_SOURCE)
\tglobalVars.appArgs.disableAddons = True
\tnvda_test_config = Path(tempfile.gettempdir()) / "nvda-ai-assistant-tests"
\tnvda_test_config.mkdir(parents=True, exist_ok=True)
\tglobalVars.appArgs.configPath = str(nvda_test_config)

\timport controlTypes  # noqa: E402, F401
\timport logHandler  # noqa: E402, F401
\timport textInfos  # noqa: E402, F401

\tREAL_NVDA_MODULES.update({{
\t\t"controlTypes": controlTypes,
\t\t"logHandler": logHandler,
\t\t"textInfos": textInfos,
\t}})


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
\t\"\"\"Skip tests requiring NVDA if sibling checkout is absent.\"\"\"
\tif not HAS_NVDA_CHECKOUT:
\t\tskip_marker = pytest.mark.skip(
\t\t\treason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."
\t\t)
\t\tfor item in items:
\t\t\tif "nvda_integration" in item.keywords:
\t\t\t\titem.add_marker(skip_marker)
"""

print("=== Testing conftest logic ===")

# Test 1: Simulated HAS_NVDA_CHECKOUT = False
with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    c_false = conftest_code_template.format(has_nvda_checkout="False")
    (d / "conftest.py").write_text(c_false, encoding="utf-8")
    
    # Test importing dummy integration test
    (d / "test_dummy_int.py").write_text('''import pytest
pytestmark = pytest.mark.nvda_integration
def test_int(): pass
''', encoding="utf-8")
    (d / "test_dummy_pure.py").write_text('''def test_pure(): pass\n''', encoding="utf-8")

    # Run mode A: -m "not nvda_integration"
    ret_a = pytest.main(["-m", "not nvda_integration", str(d)])
    print("Mode A (not nvda_integration, checkout=False):", ret_a)
    assert ret_a == 0

    # Run mode B: -m "nvda_integration"
    ret_b = pytest.main(["-m", "nvda_integration", str(d)])
    print("Mode B (nvda_integration, checkout=False):", ret_b)
    assert ret_b == 0

    # Run mode C: no marker filter (direct execution of integration test file)
    ret_c = pytest.main([str(d / "test_dummy_int.py")])
    print("Mode C (direct file, checkout=False):", ret_c)
    assert ret_c == 0

print("ALL TEST MODES PASSED SUCCESSFULLY!")
