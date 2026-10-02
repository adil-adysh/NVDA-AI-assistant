"""Regression tests for the tabbed settings UI contract.

These tests intentionally inspect the source structure so they can run in the
plain project test environment, where NVDA/wx are not installed.
"""
from __future__ import annotations

import ast

from tests.support import ADDON_ROOT
import unittest


SETTINGS_SOURCE = ADDON_ROOT / "ui" / "settings_panel.py"
CONTROLLER_SOURCE = ADDON_ROOT / "plugin" / "controller.py"


class SettingsPanelContractTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
		cls.source = SETTINGS_SOURCE.read_text(encoding="utf-8")

	def test_five_tabs_are_declared_in_user_facing_order(self) -> None:
		classes = {
			node.name: node
			for node in self.tree.body
			if isinstance(node, ast.ClassDef)
		}
		expected = [
			("AIAssistantGeneralPanel", "General"),
			("AIAssistantModelsContextPanel", "Models & Context"),
			("AIAssistantBehaviorOutputPanel", "Behavior & Output"),
			("AIAssistantRuntimePanel", "Runtime"),
			("AIAssistantDiagnosticsPanel", "Diagnostics"),
		]
		for class_name, title in expected:
			self.assertIn(class_name, classes)
			self.assertIn(title, ast.unparse(classes[class_name]))

		dialog = classes["AIAssistantSettingsDialog"]
		panel_tuple = next(
			node.value
			for node in dialog.body
			if isinstance(node, ast.Assign)
			and any(isinstance(target, ast.Name) and target.id == "_panel_classes" for target in node.targets)
		)
		self.assertEqual(
			[elt.id for elt in panel_tuple.elts if isinstance(elt, ast.Name)],
			[class_name for class_name, _title in expected],
		)

	def test_dialog_uses_notebook_and_apply_cancel_lifecycle(self) -> None:
		self.assertIn("wx.Notebook", self.source)
		self.assertIn("buttons={wx.OK, wx.CANCEL, wx.APPLY}", self.source)
		self.assertIn("def onOk", self.source)
		self.assertIn("def onApply", self.source)
		self.assertIn("def open_settings_dialog", self.source)

	def test_model_choices_queries_managed_models_without_install_step_gate(self) -> None:
		classes = {
			node.name: node
			for node in self.tree.body
			if isinstance(node, ast.ClassDef)
		}
		general_panel = classes["AIAssistantGeneralPanel"]
		methods = {
			node.name: node
			for node in general_panel.body
			if isinstance(node, ast.FunctionDef)
		}
		self.assertIn("_model_choices_for", methods)
		method_source = ast.unparse(methods["_model_choices_for"])
		self.assertIn("build_model_manager(provider_id", method_source)
		self.assertIn("manager.list_managed_models()", method_source)
		self.assertNotIn("has_install_step", method_source)

		self.assertIn("collect", methods)
		collect_source = ast.unparse(methods["collect"])
		self.assertIn("manager.resolve_model_identity", collect_source)
		self.assertNotIn("has_install_step", collect_source)

	def test_settings_menu_item_is_present(self) -> None:
		source = CONTROLLER_SOURCE.read_text(encoding="utf-8")
		self.assertIn('_("&Settings...")', source)
		self.assertIn("open_settings_dialog", source)


if __name__ == "__main__":
	unittest.main()
