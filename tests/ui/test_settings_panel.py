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

	def test_six_tabs_are_declared_in_user_facing_order(self) -> None:
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
			[class_name for class_name, _title in expected] + ["McpSettingsPanel"],
		)

	def test_mcp_settings_exposes_keyboard_accessible_per_tool_controls(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		for label in (
			'_("Configured MCP servers")',
			'_("Discovered MCP tools; selection shows approval state")',
			'_("&Approve selected tool")',
			'_("&Revoke selected tool")',
			'_("MCP connection status")',
			'_("Refresh &tools")',
			'_("Approve the external tool {tool} from server {server}?\\n\\nUntrusted tool description: {description}")',
		):
			self.assertIn(label, mcp_source)
		self.assertIn("background_tasks.submit", mcp_source)

	def test_mcp_status_announcement_helper_is_a_panel_method(self) -> None:
		mcp_tree = ast.parse((ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8"))
		panel = next(
			node for node in mcp_tree.body
			if isinstance(node, ast.ClassDef) and node.name == "McpSettingsPanel"
		)
		panel_methods = {node.name for node in panel.body if isinstance(node, ast.FunctionDef)}
		self.assertIn("_announce", panel_methods)

	def test_removing_a_server_restores_focus_to_the_list(self) -> None:
		mcp_tree = ast.parse((ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8"))
		panel = next(
			node for node in mcp_tree.body
			if isinstance(node, ast.ClassDef) and node.name == "McpSettingsPanel"
		)
		remove = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "_on_remove")
		self.assertIn("server_list.SetFocus", ast.unparse(remove))

	def test_toggling_http_server_preserves_credential_reference(self) -> None:
		mcp_tree = ast.parse((ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8"))
		panel = next(
			node for node in mcp_tree.body
			if isinstance(node, ast.ClassDef) and node.name == "McpSettingsPanel"
		)
		toggle = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "_on_toggle_enabled")
		self.assertIn("credential_ref=config.credential_ref", ast.unparse(toggle))

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

	def test_mcp_server_editor_validates_before_closing_and_keeps_safe_defaults(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		mcp_tree = ast.parse(mcp_source)
		editor = next(
			node for node in mcp_tree.body
			if isinstance(node, ast.ClassDef) and node.name == "_ServerEditor"
		)
		methods = {
			node.name: ast.unparse(node)
			for node in editor.body
			if isinstance(node, ast.FunctionDef)
		}
		self.assertIn("_on_ok", methods)
		self.assertIn("_build_config", methods)
		self.assertIn("self.EndModal(wx.ID_OK)", methods["_on_ok"])
		self.assertIn("wx.MessageBox", methods["_on_ok"])
		# The dialog-created button sizer must live on the dialog, not the panel.
		self.assertIn("outer.Add(buttons", methods["__init__"])
		self.assertNotIn("sizer.Add(buttons", methods["__init__"])
		# Destructive confirmations must not default to the destructive answer.
		self.assertIn("wx.NO_DEFAULT", mcp_source)
		self.assertEqual(mcp_source.count("wx.NO_DEFAULT"), 3)

	def test_mcp_approval_warns_about_server_declared_destructive_tools(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		self.assertIn("_declares_destructive", mcp_source)
		self.assertIn("able to change state", mcp_source)
		# The warning is an additional hint; annotations still cannot approve.
		self.assertIn("annotations are untrusted", mcp_source.lower())

	def test_mcp_tools_can_be_searched_filtered_and_previewed(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		for label in (
			'_("Search tools by name or description")',
			'_("Filter MCP tools by approval or read-only claim")',
			'_("Selected tool details and input schema:")',
			'_("Approve all read-&only")',
			"visible_definitions(",
			"details_text(",
		):
			self.assertIn(label, mcp_source)

	def test_bulk_read_only_approval_warns_that_the_claim_is_untrusted(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		self.assertIn("_on_approve_read_only", mcp_source)
		self.assertIn("unapproved_read_only(", mcp_source)
		self.assertIn("The server's read-only claim is untrusted.", mcp_source)

	def test_mcp_server_changes_return_focus_to_the_server_list(self) -> None:
		mcp_tree = ast.parse((ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8"))
		panel = next(
			node for node in mcp_tree.body
			if isinstance(node, ast.ClassDef) and node.name == "McpSettingsPanel"
		)
		edit = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "_edit_server")
		self.assertIn("server_list.SetFocus", ast.unparse(edit))
		save = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "_save_approvals")
		self.assertIn("tool_list.SetFocus", ast.unparse(save))

	def test_settings_tab_title_has_no_ampersand_mnemonic(self) -> None:
		mcp_source = (ADDON_ROOT / "ui" / "mcp_settings.py").read_text(encoding="utf-8")
		self.assertIn('title = _("MCP Servers and Tools")', mcp_source)
		self.assertNotIn('title = _("MCP Servers & Tools")', mcp_source)

	def test_tab_switching_focuses_the_first_usable_control(self) -> None:
		dialog = next(
			node for node in self.tree.body
			if isinstance(node, ast.ClassDef) and node.name == "AIAssistantSettingsDialog"
		)
		methods = {
			node.name: ast.unparse(node)
			for node in dialog.body
			if isinstance(node, ast.FunctionDef)
		}
		self.assertIn("_first_focusable", methods)
		self.assertIn("_focus_current_page", methods)
		self.assertIn("_first_focusable", methods["_focus_current_page"])
		self.assertNotIn("GetPage(self.notebook.GetSelection()).SetFocus()", methods["_on_page_changed"])

	def test_settings_menu_item_is_present(self) -> None:
		source = CONTROLLER_SOURCE.read_text(encoding="utf-8")
		self.assertIn('_("&Settings...")', source)
		self.assertIn("open_settings_dialog", source)


if __name__ == "__main__":
	unittest.main()
