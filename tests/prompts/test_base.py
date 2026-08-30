# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest

from tests.support import ADDON_ROOT, load_module, register_package


MODULE_DIR = ADDON_ROOT / "prompts"
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))


PACKAGE_NAME = "prompts_testpkg"
register_package(PACKAGE_NAME, MODULE_DIR)
base = load_module(f"{PACKAGE_NAME}.base", MODULE_DIR / "base.py")


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
