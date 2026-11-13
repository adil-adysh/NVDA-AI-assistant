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
from .mcp_tool_view import (
	FILTER_ALL,
	FILTER_APPROVED,
	FILTER_DENIED,
	FILTER_READ_ONLY,
	declares_destructive,
	details_text,
	safe_text,
	tool_heading,
	unapproved_read_only,
	visible_definitions,
)
from .task_runner import TaskHandle, background_tasks

addonHandler.initTranslation()
_ = cast(Callable[[str], str], getattr(builtins, "_", lambda value: value))


class _ServerEditor(wx.Dialog):
	"""Accessible editor for one stdio or Streamable HTTP server."""

	def __init__(
		self,
		parent: wx.Window,
		server: McpServerConfig | None = None,
		existing_ids: set[str] | None = None,
	) -> None:
		super().__init__(parent, title=_("MCP Server"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._existing = server
		self._existing_ids = existing_ids or set()
		self._validated: McpServerConfig | None = None
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
		self.arguments.SetMinSize((-1, 90))
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
		self.message.Wrap(520)
		sizer.Add(self.message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		# The dialog creates these buttons, so they belong to the dialog's sizer.
		# Adding them to the panel's sizer trips a wx assertion and prevents the
		# editor from opening at all.
		buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
		if buttons:
			outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
		self.SetSizerAndFit(outer)
		self.SetMinSize((560, 420))
		self.CentreOnParent()
		self.transport.Bind(wx.EVT_CHOICE, self._update_fields)
		self._update_fields()
		self.Bind(wx.EVT_SHOW, self._on_show)
		ok_button = self.FindWindowById(wx.ID_OK)
		if ok_button is not None:
			ok_button.Bind(wx.EVT_BUTTON, self._on_ok)

	@staticmethod
	def _field(form: wx.FlexGridSizer, parent: wx.Window, label: str, value: str) -> wx.TextCtrl:
		form.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		control = wx.TextCtrl(parent, value=value)
		control.SetName(label.removesuffix(":"))
		form.Add(control, 1, wx.EXPAND)
		return control

	def _on_show(self, event: wx.ShowEvent) -> None:
		event.Skip()
		if event.IsShown():
			# ShowModal focuses the default button after construction. Move focus
			# to the first editable field once the dialog is actually visible.
			wx.CallAfter(self.server_id.SetFocus)

	def _on_ok(self, event: wx.CommandEvent) -> None:
		"""Validate before closing so a typo does not discard the whole form."""
		try:
			config = self._build_config()
			if config.server_id in self._existing_ids:
				raise ValueError(_("A server with that ID is already configured."))
		except ValueError as error:
			wx.MessageBox(str(error), _("Invalid MCP server"), wx.OK | wx.ICON_ERROR, parent=self)
			return
		self._validated = config
		self.EndModal(wx.ID_OK)

	def _update_fields(self, _event: wx.CommandEvent | None = None) -> None:
		is_stdio = self.transport.GetSelection() == 0
		self.command.Enable(is_stdio)
		self.arguments.Enable(is_stdio)
		self.url.Enable(not is_stdio)
		self.auth_token.Enable(not is_stdio)
		self.clear_token.Enable(not is_stdio and bool(self._existing and self._existing.credential_ref))

	def get_config(self) -> McpServerConfig:
		if self._validated is not None:
			return self._validated
		return self._build_config()

	def _build_config(self) -> McpServerConfig:
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

	title = _("MCP Servers and Tools")

	def __init__(self, parent: wx.Window, catalog: object, registry: object, executor: object) -> None:
		super().__init__(parent, style=wx.TAB_TRAVERSAL)
		self._catalog = catalog
		self._registry = registry
		self._executor = executor
		self._configs = list(get_mcp_servers())
		self._approved = set(get_mcp_approved_tool_ids())
		self._busy: TaskHandle[object] | None = None
		self._tool_ids: list[str] = []
		self._available_tools: list[object] = []
		self._visible_tools: list[object] = []
		self._visible_tool_ids: list[str] = []
		self._filter_mode = FILTER_ALL
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
		filter_row = wx.BoxSizer(wx.HORIZONTAL)
		self.tool_search = wx.TextCtrl(self)
		self.tool_search.SetHint(_("Search tools by name or description"))
		self.tool_search.SetName(_("Search MCP tools by name or description"))
		self.tool_filter = wx.Choice(
			self,
			choices=[
				_("All tools"),
				_("Approved only"),
				_("Not approved"),
				_("Server-declared read-only"),
			],
		)
		self.tool_filter.SetSelection(0)
		self.tool_filter.SetName(_("Filter MCP tools by approval or read-only claim"))
		filter_row.Add(self.tool_search, 1, wx.EXPAND | wx.RIGHT, 4)
		filter_row.Add(self.tool_filter, 0, wx.EXPAND)
		right.Add(filter_row, 0, wx.EXPAND | wx.BOTTOM, 6)
		self.tool_list = wx.ListBox(self, choices=[])
		self.tool_list.SetName(_("Discovered MCP tools; selection shows approval state"))
		right.Add(self.tool_list, 1, wx.EXPAND | wx.BOTTOM, 6)
		self.tool_summary = wx.StaticText(self, label=_("No tools discovered."))
		self.tool_summary.SetName(_("MCP tool count and approval summary"))
		right.Add(self.tool_summary, 0, wx.BOTTOM, 6)
		tool_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.approve_button = wx.Button(self, label=_("&Approve selected tool"))
		self.revoke_button = wx.Button(self, label=_("&Revoke selected tool"))
		self.approve_all_read_only_button = wx.Button(self, label=_("Approve all read-&only"))
		self.approve_button.Bind(wx.EVT_BUTTON, self._on_approve)
		self.revoke_button.Bind(wx.EVT_BUTTON, self._on_revoke)
		self.approve_all_read_only_button.Bind(wx.EVT_BUTTON, self._on_approve_read_only)
		tool_buttons.Add(self.approve_button, 0, wx.RIGHT, 4)
		tool_buttons.Add(self.revoke_button, 0, wx.RIGHT, 4)
		tool_buttons.Add(self.approve_all_read_only_button)
		right.Add(tool_buttons, 0, wx.EXPAND | wx.BOTTOM, 6)
		right.Add(wx.StaticText(self, label=_("Selected tool details and input schema:")), 0, wx.BOTTOM, 4)
		self.tool_details = wx.TextCtrl(
			self,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
		)
		self.tool_details.SetMinSize((-1, 170))
		self.tool_details.SetName(_("Selected MCP tool details and input schema"))
		right.Add(self.tool_details, 0, wx.EXPAND)
		columns.Add(right, 1, wx.ALL | wx.EXPAND, 8)
		outer.Add(columns, 1, wx.EXPAND)
		self.status = wx.StaticText(self, label=_("Disconnected"))
		self.status.SetName(_("MCP connection status"))
		outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
		self.SetSizer(outer)
		self.server_list.Bind(wx.EVT_LISTBOX, self._on_server_selected)
		self.tool_list.Bind(wx.EVT_LISTBOX, self._on_tool_selected)
		self.tool_search.Bind(wx.EVT_TEXT, self._on_tool_filter_changed)
		self.tool_filter.Bind(wx.EVT_CHOICE, self._on_tool_filter_changed)
		self._refresh_servers()
		self._refresh_tools()
		self._update_tool_actions()

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
		self.server_list.Set([
			f"{server.name} ({server.server_id}) — {self._server_state_label(server)}"
			for server in self._configs
		])
		if selected_id:
			for index, server in enumerate(self._configs):
				if server.server_id == selected_id:
					self.server_list.SetSelection(index)
					break
		self._on_server_selected(None)

	def _server_state_label(self, server: McpServerConfig) -> str:
		if self._connected(server.server_id):
			return _("connected")
		return _("enabled") if server.enabled else _("disabled")

	def _refresh_tools(self, selected_tool_id: str | None = None) -> None:
		selected = self._selected_config()
		server_id = selected[1].server_id if selected else None
		definitions = getattr(self._registry, "get_enabled_definitions")()
		self._available_tools = [
			definition for definition in definitions if definition.provider_id == f"mcp:{server_id}"
		]
		self._tool_ids = [definition.tool_id for definition in self._available_tools]
		self._apply_tool_filter(selected_tool_id)

	def _apply_tool_filter(self, selected_tool_id: str | None = None) -> None:
		"""Rebuild the visible list without reconnecting or re-reading the server."""

		filter_modes = [FILTER_ALL, FILTER_APPROVED, FILTER_DENIED, FILTER_READ_ONLY]
		selection = self.tool_filter.GetSelection()
		self._filter_mode = filter_modes[selection] if 0 <= selection < len(filter_modes) else FILTER_ALL
		self._visible_tools = visible_definitions(
			self._available_tools,
			self._approved,
			self.tool_search.GetValue(),
			self._filter_mode,
		)
		self._visible_tool_ids = [str(getattr(tool, "tool_id", "")) for tool in self._visible_tools]
		self.tool_list.Set([
			self._tool_label(definition)
			for definition in self._visible_tools
		])
		approved_count = sum(1 for tool_id in self._tool_ids if tool_id in self._approved)
		if self._tool_ids:
			self.tool_summary.SetLabel(
				_("{count} tools discovered; {approved} approved; showing {visible}.").format(
					count=len(self._tool_ids),
					approved=approved_count,
					visible=len(self._visible_tools),
				)
			)
		else:
			self.tool_summary.SetLabel(_("No tools discovered."))
		if self._visible_tool_ids:
			index = (
				self._visible_tool_ids.index(selected_tool_id)
				if selected_tool_id in self._visible_tool_ids
				else 0
			)
			self.tool_list.SetSelection(index)
			self.tool_list.EnsureVisible(index)
		self._on_tool_selected(None)
		self._update_tool_actions()

	def _tool_label(self, definition: object) -> str:
		heading = tool_heading(definition)
		name = safe_text(
			getattr(definition, "provider_tool_name", "") or getattr(definition, "name", ""),
			120,
		)
		label = heading if heading == name or not name else f"{heading} ({name})"
		status = _("approved") if getattr(definition, "tool_id", "") in self._approved else _("denied")
		description = _safe_tool_description(getattr(definition, "description", ""), 100)
		return f"{label} — {status} — {description}" if description else f"{label} — {status}"

	def _update_tool_actions(self) -> None:
		selected = self._selected_tool_id()
		self.approve_button.Enable(selected is not None and self._busy is None)
		self.revoke_button.Enable(selected is not None and self._busy is None)
		candidates = unapproved_read_only(self._available_tools, self._approved)
		self.approve_all_read_only_button.Enable(bool(candidates) and self._busy is None)
		self.approve_all_read_only_button.SetLabel(
			_("Approve all read-&only ({count})").format(count=len(candidates))
			if candidates
			else _("Approve all read-&only")
		)

	def _on_tool_selected(self, _event: wx.CommandEvent | None) -> None:
		tool_id = self._selected_tool_id()
		definition = self._tool_by_id(tool_id)
		if definition is None:
			self.tool_details.SetValue("")
			return
		self.tool_details.SetValue(details_text(definition, tool_id in self._approved))
		self.tool_details.SetInsertionPoint(0)

	def _on_tool_filter_changed(self, _event: wx.CommandEvent) -> None:
		self._apply_tool_filter(self._selected_tool_id())

	def _tool_by_id(self, tool_id: str | None) -> object | None:
		if not tool_id:
			return None
		return next(
			(tool for tool in self._available_tools if getattr(tool, "tool_id", "") == tool_id),
			None,
		)

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
		existing_ids = {
			server.server_id
			for position, server in enumerate(self._configs)
			if position != index
		}
		dialog = _ServerEditor(self, current, existing_ids=existing_ids)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			updated = dialog.get_config()
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
			self.server_list.SetFocus()
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
		if wx.MessageBox(_("Remove {name} and its saved tool approvals?").format(name=config.name), _("Remove MCP server"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		self._configs.pop(index)
		self._approved = {tool_id for tool_id in self._approved if not tool_id.startswith(f"mcp:mcp:{config.server_id}:")}
		set_mcp_server_token(config.server_id, "")
		set_mcp_servers(self._configs)
		set_mcp_approved_tool_ids(sorted(self._approved))
		self._apply_policy()
		self._refresh_servers()
		self.server_list.SetFocus()

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
		self._update_tool_actions()

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
		return self._visible_tool_ids[index] if 0 <= index < len(self._visible_tool_ids) else None

	def _on_approve(self, _event: wx.CommandEvent) -> None:
		tool_id = self._selected_tool_id()
		selected = self._selected_config()
		if not tool_id or selected is None:
			return
		definition = self._tool_by_id(tool_id)
		if definition is None:
			return
		description = _safe_tool_description(getattr(definition, "description", "")) or _("No description was provided.")
		prompt = _("Approve the external tool {tool} from server {server}?\n\nUntrusted tool description: {description}").format(
			tool=definition.provider_tool_name,
			server=selected[1].name,
			description=description,
		)
		if _declares_destructive(definition):
			prompt += _("\n\nThe server describes this tool as able to change state. Approve it only if you trust this server.")
		if wx.MessageBox(prompt, _("Approve MCP tool"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent=self) == wx.YES:
			self._approved.add(tool_id)
			self._save_approvals()

	def _on_revoke(self, _event: wx.CommandEvent) -> None:
		tool_id = self._selected_tool_id()
		if tool_id:
			self._approved.discard(tool_id)
			self._save_approvals()

	def _on_approve_read_only(self, _event: wx.CommandEvent) -> None:
		selected = self._selected_config()
		if selected is None:
			return
		candidates = unapproved_read_only(self._available_tools, self._approved)
		if not candidates:
			return
		names = [str(getattr(tool, "provider_tool_name", "") or getattr(tool, "name", "")) for tool in candidates]
		shown = names[:12]
		name_list = "\n".join(f"- {name}" for name in shown)
		if len(names) > len(shown):
			name_list += _("\n- …and {count} more").format(count=len(names) - len(shown))
		prompt = _(
			"Approve {count} tools that server {server} declares read-only?\n\n{names}\n\n"
			"The server's read-only claim is untrusted. Approving still grants each tool "
			"permission to run; review and revoke individual tools if you do not trust this server."
		).format(count=len(candidates), server=selected[1].name, names=name_list)
		if wx.MessageBox(prompt, _("Approve read-only MCP tools"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent=self) != wx.YES:
			return
		for tool in candidates:
			tool_id = str(getattr(tool, "tool_id", "") or "")
			if tool_id:
				self._approved.add(tool_id)
		self._save_approvals()

	def _save_approvals(self) -> None:
		selected_tool_id = self._selected_tool_id()
		set_mcp_approved_tool_ids(sorted(self._approved))
		self._apply_policy()
		self._refresh_tools(selected_tool_id)
		self.tool_list.SetFocus()
		self._announce(_("MCP tool permissions updated."))

	def _apply_policy(self) -> None:
		getattr(self._executor, "set_policy")(
			DefaultToolPermissionPolicy(approved_tool_ids=frozenset(self._approved))
		)

	def _operation_failed(self, error: Exception) -> None:
		self._busy = None
		self._refresh_servers(self._selected_config()[1].server_id if self._selected_config() else None)
		self._update_tool_actions()
		message = getattr(error, "safe_message", None)
		if not isinstance(message, str) or not message.strip():
			message = _("MCP operation failed. Review the server settings and try again.")
		self.status.SetLabel(message)
		self._announce(message)

	@staticmethod
	def _announce(message: str) -> None:
		try:
			from .nvda_ui import message as speak_message
			speak_message(message)
		except Exception:
			pass


def _declares_destructive(definition: object) -> bool:
	"""Return the server's destructive hint, used only as an approval warning.

	Annotations are untrusted display data; they never grant permission.  A
	server that explicitly labels a tool destructive gets a stronger warning so
	the user does not approve a state-changing bridge tool as if it were a
	read-only query.
	"""
	return declares_destructive(definition)


def _safe_tool_description(value: str, limit: int = 160) -> str:
	"""Bound and flatten an untrusted description before rendering or speaking."""
	return safe_text(value, limit)
