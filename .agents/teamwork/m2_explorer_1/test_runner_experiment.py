import pytest
import tempfile
import pathlib

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

conftest_code = """import pytest

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

with tempfile.TemporaryDirectory() as tmp_dir:
    d = pathlib.Path(tmp_dir)
    (d / "conftest.py").write_text(conftest_code, encoding="utf-8")
    (d / "test_browser_field_parser.py").write_text(parser_code, encoding="utf-8")
    (d / "test_pure.py").write_text("def test_pure(): pass\n", encoding="utf-8")

    print("=== Case 1: default -m 'not nvda_integration' ===")
    ret1 = pytest.main(["-m", "not nvda_integration", str(d)])
    print("Case 1 ret:", ret1)

    print("=== Case 2: -m nvda_integration (missing checkout) ===")
    ret2 = pytest.main(["-m", "nvda_integration", str(d)])
    print("Case 2 ret:", ret2)

    print("=== Case 3: direct file execution (missing checkout) ===")
    ret3 = pytest.main([str(d / "test_browser_field_parser.py")])
    print("Case 3 ret:", ret3)
