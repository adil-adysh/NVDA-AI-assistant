# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))


PACKAGE_NAME = "prompts_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


def _load_module(module_name: str, file_name: str):
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


base = _load_module("base", "base.py")


class PromptTemplateResolutionTests(unittest.TestCase):
	def test_region_falls_back_to_base_language_folder(self) -> None:
		rendered = base.render_prompt_template("system_prompt.jinja2", language="fr_FR")

		self.assertIn("assistant d'accessibilite NVDA", rendered)

	def test_hyphenated_locale_matches_underscore_folder(self) -> None:
		rendered = base.render_prompt_template("system_prompt.jinja2", language="zh-CN")

		self.assertIn("NVDA 无障碍助手", rendered)

	def test_exact_region_folder_is_used(self) -> None:
		rendered = base.render_prompt_template("system_prompt.jinja2", language="pt_BR")

		self.assertIn("assistente de acessibilidade do NVDA", rendered)

	def test_base_language_folder_is_used_for_variant_pt(self) -> None:
		rendered = base.render_prompt_template("system_prompt.jinja2", language="pt_PT")

		self.assertIn("assistente de acessibilidade do NVDA", rendered)

	def test_czech_locale_falls_back_to_cs_folder(self) -> None:
		rendered = base.render_prompt_template("system_prompt.jinja2", language="cs_CZ")

		self.assertIn("asistent přístupnosti pro NVDA", rendered)


if __name__ == "__main__":
	unittest.main()
