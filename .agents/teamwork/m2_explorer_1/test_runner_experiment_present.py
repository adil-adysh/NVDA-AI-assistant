import pytest
import tempfile
import pathlib
import sys
import gettext
import builtins

PROJECT_ROOT = pathlib.Path.cwd()
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"

nvda_source_escaped = str(NVDA_SOURCE).replace("\\", "\\\\")

parser_code = """from __future__ import annotations
import unittest
import pytest

pytestmark = pytest.mark.nvda_integration

try:
    import controlTypes
    Role = controlTypes.Role
except ImportError:
    controlTypes = None
    Role = None

class BrowserFieldParserTests(unittest.TestCase):
    def test_one(self):
        self.assertIsNotNone(Role)
"""

conftest_code_present = f"""import pytest
import sys
import builtins
import gettext

builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

sys.path.insert(0, "{nvda_source_escaped}")

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

with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    (d / "conftest.py").write_text(conftest_code_present, encoding="utf-8")
    (d / "test_browser_field_parser.py").write_text(parser_code, encoding="utf-8")
    (d / "test_pure.py").write_text("def test_pure(): pass\n", encoding="utf-8")

    print("=== Case 5: HAS_NVDA_CHECKOUT = True, -m 'nvda_integration' ===")
    ret5 = pytest.main(["-m", "nvda_integration", str(d)])
    print("Case 5 ret:", ret5)
