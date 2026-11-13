"""Keyboard-accessible MCP server and per-tool permission controls."""
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import cast

import addonHandler
import wx

from ..config.mcp_servers import McpServerConfig
from ..config.settings import (
	get_mcp_approved_tool_ids,
	get_mcp_servers,
	set_mcp_approved_tool_ids,
	set_mcp_server_token,
	set_mcp_servers,
)
from ..tools.policy import DefaultToolPermissionPolicy
from .task_runner import TaskHandle, background_tasks

addonHandler.initTranslation()
_ = cast(Callable[[str], str], getattr(builtins, "_", lambda value: value))


class _ServerEditor(wx.Dialog):
	"""Accessible editor for one stdio or Streamable HTTP server."""

	def __init__(self, parent: wx.Window, server: McpServerConfig | None = None) -> None:
		super().__init__(parent, title=_("MCP Server"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._existing = server
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		form = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
		form.AddGrowableCol(1, 1)
		self.server_id = self._field(form, panel, _("Server ID:"), server.server_id if server else "")
		if server is not None:
			self.server_id.SetEditable(False)
		self.name = self._field(form, panel, _("Display name:"), server.name if server else "")
		form.Add(wx.StaticText(panel, label=_("Transport:")), 0, wx.ALIGN_CENTER_VERTICAL)
		self.transport = wx.Choice(panel, choices=[_("Standard I/O"), _("Streamable HTTP")])
		self.transport.SetName(_("Transport"))
		self.transport.SetSelection(1 if server and server.transport == "streamable_http" else 0)
		form.Add(self.transport, 1, wx.EXPAND)
		self.command = self._field(form, panel, _("Executable path:"), server.command if server and server.transport == "stdio" else "")
		self.arguments = wx.TextCtrl(panel, value="\n".join(server.args) if server and server.transport == "stdio" else "", style=wx.TE_MULTILINE)
		self.arguments.SetName(_("Arguments, one per line"))
		form.Add(wx.StaticText(panel, label=_("Arguments, one per line:")), 0, wx.ALIGN_TOP)
		form.Add(self.arguments, 1, wx.EXPAND)
		self.url = self._field(form, panel, _("Streamable HTTP URL:"), server.url if server and server.transport == "streamable_http" else "")
		self.auth_token = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
		self.auth_token.SetName(_("HTTP bearer token; leave blank to keep the saved token"))
		form.Add(wx.StaticText(panel, label=_("HTTP bearer token:")), 0, wx.ALIGN_CENTER_VERTICAL)
		form.Add(self.auth_token, 1, wx.EXPAND)
		self.clear_token = wx.CheckBox(panel, label=_("Clear saved bearer token"))
		self.clear_token.SetName(_("Clear saved HTTP bearer token"))
		form.AddSpacer(1)
		form.Add(self.clear_token, 1, wx.EXPAND)
		sizer.Add(form, 1, wx.ALL | wx.EXPAND, 12)
		self.message = wx.StaticText(panel, label=_("HTTP must use HTTPS, or unauthenticated HTTP on localhost/loopback. Saved bearer tokens use Windows DPAPI. Do not put secrets in server URLs or stdio arguments."))
		self.message.SetName(_("Connection security guidance"))
		sizer.Add(self.message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
		if buttons:
			sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetMinSize((560, 360))
		self.transport.Bind(wx.EVT_CHOICE, self._update_fields)
		self._update_fields()
		self.server_id.SetFocus()

	@staticmethod
	def _field(form: wx.FlexGridSizer, parent: wx.Window, label: str, value: str) -> wx.TextCtrl:
		form.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		control = wx.TextCtrl(parent, value=value)
		control.SetName(label.removesuffix(":"))
		form.Add(control, 1, wx.EXPAND)
		return control

	def _update_fields(self, _event: wx.CommandEvent | None = None) -> None:
		is_stdio = self.transport.GetSelection() == 0
		self.command.Enable(is_stdio)
		self.arguments.Enable(is_stdio)
		self.url.Enable(not is_stdio)
		self.auth_token.Enable(not is_stdio)
		self.clear_token.Enable(not is_stdio and bool(self._existing and self._existing.credential_ref))

	def get_config(self) -> McpServerConfig:
		is_stdio = self.transport.GetSelection() == 0
		base = {
			"server_id": self.server_id.GetValue().strip(),
			"name": self.name.GetValue().strip() or self.server_id.GetValue().strip(),
			"transport": "stdio" if is_stdio else "streamable_http",
			"enabled": self._existing.enabled if self._existing else True,
		}
		if is_stdio:
			base.update(command=self.command.GetValue().strip(), args=self.arguments.GetValue().splitlines())
		else:
			base["url"] = self.url.GetValue().strip()
			if self.auth_token.GetValue():
				base["credential_ref"] = base["server_id"]
			elif self._existing and self._existing.credential_ref and not self.clear_token.GetValue():
				base["credential_ref"] = self._existing.credential_ref
		return McpServerConfig.from_dict(base)

	def get_token(self) -> str:
		return self.auth_token.GetValue()


class McpSettingsPanel(wx.Panel):
	"""Accessible server list, status, tool inspection and approval controls."""

	title = _("MCP Servers & Tools")

	def __init__(self, parent: wx.Window, catalog: object, registry: object, executor: object) -> None:
		super().__init__(parent, style=wx.TAB_TRAVERSAL)
		self._catalog = catalog
		self._registry = registry
		self._executor = executor
		self._configs = list(get_mcp_servers())
		self._approved = set(get_mcp_approved_tool_ids())
		self._busy: TaskHandle[object] | None = None
		self._tool_ids: list[str] = []
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(wx.StaticText(self, label=_("External MCP tools are denied until you approve each tool. Server annotations cannot grant permission.")), 0, wx.ALL | wx.EXPAND, 8)
		outer.Add(wx.StaticText(self, label=_("Server and permission changes are saved immediately.")), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
		columns = wx.BoxSizer(wx.HORIZONTAL)
		left = wx.BoxSizer(wx.VERTICAL)
		left.Add(wx.StaticText(self, label=_("Configured servers:")), 0, wx.BOTTOM, 4)
		self.server_list = wx.ListBox(self, choices=[])
		self.server_list.SetName(_("Configured MCP servers"))
		left.Add(self.server_list, 1, wx.EXPAND | wx.BOTTOM, 6)
		server_buttons = wx.BoxSizer(wx.HORIZONTAL)
		for label, handler in ((_("&Add..."), self._on_add), (_("&Edit..."), self._on_edit), (_("&Remove"), self._on_remove)):
			button = wx.Button(self, label=label)
			button.Bind(wx.EVT_BUTTON, handler)
			if label == _("&Edit..."):
				self.edit_button = button
			elif label == _("&Remove"):
				self.remove_button = button
			server_buttons.Add(button, 0, wx.RIGHT, 4)
		left.Add(server_buttons, 0, wx.EXPAND)
		connection_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.connect_button = wx.Button(self, label=_("&Connect"))
		self.disconnect_button = wx.Button(self, label=_("&Disconnect"))
		self.refresh_button = wx.Button(self, label=_("Refresh &tools"))
		self.toggle_button = wx.Button(self, label=_("&Disable"))
		self.connect_button.Bind(wx.EVT_BUTTON, self._on_connect)
		self.disconnect_button.Bind(wx.EVT_BUTTON, self._on_disconnect)
		self.refresh_button.Bind(wx.EVT_BUTTON, self._on_refresh)
		self.toggle_button.Bind(wx.EVT_BUTTON, self._on_toggle_enabled)
		connection_buttons.Add(self.connect_button, 0, wx.RIGHT, 4)
		connection_buttons.Add(self.disconnect_button, 0, wx.RIGHT, 4)
		connection_buttons.Add(self.refresh_button, 0, wx.RIGHT, 4)
		connection_buttons.Add(self.toggle_button)
		left.Add(connection_buttons, 0, wx.TOP, 6)
		columns.Add(left, 1, wx.ALL | wx.EXPAND, 8)
		right = wx.BoxSizer(wx.VERTICAL)
		right.Add(wx.StaticText(self, label=_("Discovered tools:")), 0, wx.BOTTOM, 4)
		self.tool_list = wx.ListBox(self, choices=[])
		self.tool_list.SetName(_("Discovered MCP tools; selection shows approval state"))
		right.Add(self.tool_list, 1, wx.EXPAND | wx.BOTTOM, 6)
		tool_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.approve_button = wx.Button(self, label=_("&Approve selected tool"))
		self.revoke_button = wx.Button(self, label=_("&Revoke selected tool"))
		self.approve_button.Bind(wx.EVT_BUTTON, self._on_approve)
		self.revoke_button.Bind(wx.EVT_BUTTON, self._on_revoke)
		tool_buttons.Add(self.approve_button, 0, wx.RIGHT, 4)
		tool_buttons.Add(self.revoke_button)
		right.Add(tool_buttons, 0, wx.EXPAND)
		columns.Add(right, 1, wx.ALL | wx.EXPAND, 8)
		outer.Add(columns, 1, wx.EXPAND)
		self.status = wx.StaticText(self, label=_("Disconnected"))
		self.status.SetName(_("MCP connection status"))
		outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
		self.SetSizer(outer)
		self.server_list.Bind(wx.EVT_LISTBOX, self._on_server_selected)
		self._refresh_servers()
		self._refresh_tools()

	def collect(self, _values: dict[str, object]) -> None:
		"""MCP configuration actions persist atomically when invoked."""
		return

	def _alive(self) -> bool:
		return not self.IsBeingDeleted()

	def _selected_config(self) -> tuple[int, McpServerConfig] | None:
		index = self.server_list.GetSelection()
		if 0 <= index < len(self._configs):
			return index, self._configs[index]
		return None

	def _refresh_servers(self, selected_id: str | None = None) -> None:
		self.server_list.Set([f"{server.name} ({server.server_id}) — {_("enabled") if server.enabled else _("disabled")}" for server in self._configs])
		if selected_id:
			for index, server in enumerate(self._configs):
				if server.server_id == selected_id:
					self.server_list.SetSelection(index)
					break
		self._on_server_selected(None)

	def _refresh_tools(self) -> None:
		selected = self._selected_config()
		server_id = selected[1].server_id if selected else None
		definitions = getattr(self._registry, "get_enabled_definitions")()
		available = [definition for definition in definitions if definition.provider_id == f"mcp:{server_id}"]
		self._tool_ids = [definition.tool_id for definition in available]
		self.tool_list.Set([
			f"{definition.provider_tool_name} — {_("approved") if definition.tool_id in self._approved else _("denied")} — {_("Description")}: {_safe_tool_description(definition.description)}" for definition in available
		])
		if self._tool_ids:
			self.tool_list.SetSelection(0)

	def _connected(self, server_id: str) -> bool:
		is_connected = getattr(self._catalog, "is_connected", None)
		if callable(is_connected):
			return bool(is_connected(server_id))
		return any(definition.provider_id == f"mcp:{server_id}" for definition in getattr(self._registry, "get_enabled_definitions")())

	def _on_server_selected(self, _event: wx.CommandEvent | None) -> None:
		selected = self._selected_config()
		connected = selected is not None and self._connected(selected[1].server_id)
		self.connect_button.Enable(selected is not None and selected[1].enabled and not connected and self._busy is None)
		self.disconnect_button.Enable(bool(connected) and self._busy is None)
		self.refresh_button.Enable(bool(connected) and self._busy is None)
		self.toggle_button.Enable(selected is not None and self._busy is None)
		self.toggle_button.SetLabel(_("&Disable") if selected and selected[1].enabled else _("&Enable"))
		self.edit_button.Enable(selected is not None and not connected and self._busy is None)
		self.remove_button.Enable(selected is not None and not connected and self._busy is None)
		self._refresh_tools()
		if selected is None:
			self.status.SetLabel(_("Select an MCP server."))
		else:
			state = _("Connected") if connected else (_("Enabled, disconnected") if selected[1].enabled else _("Disabled"))
			self.status.SetLabel(_("{name}: {state}").format(name=selected[1].name, state=state))

	def _on_add(self, _event: wx.CommandEvent) -> None:
		self._edit_server(None)

	def _on_edit(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is not None and not self._connected(selected[1].server_id):
			self._edit_server(selected[0])

	def _edit_server(self, index: int | None) -> None:
		current = self._configs[index] if index is not None else None
		dialog = _ServerEditor(self, current)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			try:
				updated = dialog.get_config()
				if any(i != index and item.server_id == updated.server_id for i, item in enumerate(self._configs)):
					raise ValueError(_("A server with that ID is already configured."))
			except ValueError as error:
				wx.MessageBox(str(error), _("Invalid MCP server"), wx.OK | wx.ICON_ERROR, parent=self)
				return
			old = None
			if index is None:
				self._configs.append(updated)
			else:
				old = self._configs[index]
				if (old.transport, old.command, old.args, old.url) != (updated.transport, updated.command, updated.args, updated.url):
					self._approved = {tool_id for tool_id in self._approved if not tool_id.startswith(f"mcp:mcp:{old.server_id}:")}
					set_mcp_approved_tool_ids(sorted(self._approved))
					self._apply_policy()
				self._configs[index] = updated
			if dialog.get_token():
				set_mcp_server_token(updated.server_id, dialog.get_token())
			elif dialog.clear_token.GetValue() or (old and old.credential_ref and not updated.credential_ref):
				set_mcp_server_token(updated.server_id, "")
			set_mcp_servers(self._configs)
			self._refresh_servers(updated.server_id)
		finally:
			dialog.Destroy()

	def _on_remove(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is None:
			return
		index, config = selected
		if self._connected(config.server_id):
			wx.MessageBox(_("Disconnect the server before removing it."), _("MCP server is connected"), wx.OK | wx.ICON_INFORMATION, parent=self)
			return
		if wx.MessageBox(_("Remove {name} and its saved tool approvals?").format(name=config.name), _("Remove MCP server"), wx.YES_NO | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		self._configs.pop(index)
		self._approved = {tool_id for tool_id in self._approved if not tool_id.startswith(f"mcp:mcp:{config.server_id}:")}
		set_mcp_server_token(config.server_id, "")
		set_mcp_servers(self._configs)
		set_mcp_approved_tool_ids(sorted(self._approved))
		self._apply_policy()
		self._refresh_servers()

	def _submit(self, work: Callable[[], object], success: str) -> None:
		self.connect_button.Disable()
		self.disconnect_button.Disable()
		self.refresh_button.Disable()
		self.toggle_button.Disable()
		self.edit_button.Disable()
		self.remove_button.Disable()
		self.status.SetLabel(_("Working…"))
		def completed(_result: object) -> None:
			self._busy = None
			self._refresh_servers(self._selected_config()[1].server_id if self._selected_config() else None)
			self._refresh_tools()
			self.status.SetLabel(success)
			self._announce(success)
		self._busy = background_tasks.submit(
			lambda _cancel: work(),
			on_success=completed,
			on_error=self._operation_failed,
			is_alive=self._alive,
			task_name="MCP server configuration",
		)

	def _on_connect(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is not None:
			config = selected[1]
			self._submit(lambda: getattr(self._catalog, "connect_config")(config), _("Connected to {name}.").format(name=config.name))

	def _on_disconnect(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is not None:
			config = selected[1]
			self._submit(lambda: getattr(self._catalog, "disconnect")(config.server_id), _("Disconnected from {name}.").format(name=config.name))

	def _on_refresh(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is not None:
			config = selected[1]
			self._submit(
				lambda: getattr(self._catalog, "refresh_connected")(config.server_id),
				_("Refreshed tools from {name}.").format(name=config.name),
			)

	def _on_toggle_enabled(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is None:
			return
		index, config = selected
		updated = McpServerConfig(
			server_id=config.server_id,
			name=config.name,
			transport=config.transport,
			enabled=not config.enabled,
			command=config.command,
			args=config.args,
			url=config.url,
			credential_ref=config.credential_ref,
		)
		self._configs[index] = updated
		set_mcp_servers(self._configs)
		if config.enabled and self._connected(config.server_id):
			self._submit(
				lambda: getattr(self._catalog, "disconnect")(config.server_id),
				_("Disabled {name} and disconnected its tools.").format(name=config.name),
			)
		else:
			self._refresh_servers(config.server_id)
			self._announce(_("MCP server setting updated."))

	def _selected_tool_id(self) -> str | None:
		index = self.tool_list.GetSelection()
		return self._tool_ids[index] if 0 <= index < len(self._tool_ids) else None

	def _on_approve(self, _event: wx.CommandEvent) -> None:
		tool_id = self._selected_tool_id()
		selected = self._selected_config()
		if not tool_id or selected is None:
			return
		definition = next((item for item in getattr(self._registry, "get_enabled_definitions")() if item.tool_id == tool_id), None)
		if definition is None:
			return
		description = _safe_tool_description(definition.description) or _("No description was provided.")
		prompt = _("Approve the external tool {tool} from server {server}?\n\nUntrusted tool description: {description}").format(
			tool=definition.provider_tool_name,
			server=selected[1].name,
			description=description,
		)
		if wx.MessageBox(prompt, _("Approve MCP tool"), wx.YES_NO | wx.ICON_WARNING, parent=self) == wx.YES:
			self._approved.add(tool_id)
			self._save_approvals()

	def _on_revoke(self, _event: wx.CommandEvent) -> None:
		tool_id = self._selected_tool_id()
		if tool_id:
			self._approved.discard(tool_id)
			self._save_approvals()

	def _save_approvals(self) -> None:
		set_mcp_approved_tool_ids(sorted(self._approved))
		self._apply_policy()
		self._refresh_tools()
		self._announce(_("MCP tool permissions updated."))

	def _apply_policy(self) -> None:
		getattr(self._executor, "set_policy")(
			DefaultToolPermissionPolicy(approved_tool_ids=frozenset(self._approved))
		)

	def _operation_failed(self, _error: Exception) -> None:
		self._busy = None
		self._refresh_servers(self._selected_config()[1].server_id if self._selected_config() else None)
		self.status.SetLabel(_("MCP operation failed. Review the server settings and try again."))
		self._announce(self.status.GetLabel())

	@staticmethod
	def _announce(message: str) -> None:
		try:
			from .nvda_ui import message as speak_message
			speak_message(message)
		except Exception:
			pass


def _safe_tool_description(value: str) -> str:
	"""Bound and flatten an untrusted description before rendering or speaking."""
	if not isinstance(value, str):
		return ""
	text = " ".join("".join(char if char.isprintable() else " " for char in value).split())
	return text[:160]
