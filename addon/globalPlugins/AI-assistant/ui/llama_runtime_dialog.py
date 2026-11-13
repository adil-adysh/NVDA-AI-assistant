"""Accessible per-model llama runtime settings; persistence stays in Python services."""
import wx
from gui import guiHelper
from wx.lib import scrolledpanel

from ..core.llama_options import OPTION_BY_KEY, validate_options
from ..core.translation import _

EDITABLE_KEYS = ("ctx-size", "gpu-layers", "flash-attn", "cache-type-k", "cache-type-v", "moe-cache-mib")


def runtime_field_state(options, supported, *, provider_context=0):
	return {key: {"stored": options.get(key), "supported": key in supported,
		"effective": options.get(key) or (str(provider_context) if key == "ctx-size" and provider_context > 0 else None),
		"origin": "configuration" if key in options else "provider" if key == "ctx-size" and provider_context > 0 else "runtime"}
		for key in OPTION_BY_KEY}


def compose_options(existing, values, kv_placement, moe_placement, moe_layers):
	"""Replace edited values while retaining other supported imported settings."""
	options = {key: value for key, value in existing.items()
		if key not in {*EDITABLE_KEYS, "kv-offload", "no-kv-offload", "cpu-moe", "n-cpu-moe"}}
	options.update({key: value.strip() for key, value in values.items() if value.strip()})
	if kv_placement == 1:
		options["kv-offload"] = "true"
	elif kv_placement == 2:
		options["no-kv-offload"] = "true"
	if moe_placement == 1:
		options["cpu-moe"] = "true"
	elif moe_placement == 2:
		options["n-cpu-moe"] = moe_layers.strip()
	return validate_options(options)


class LlamaRuntimeDialog(wx.Dialog):
	def __init__(self, parent, model_id, options, supported, *, provider_context=0):
		super().__init__(parent, title=_("Runtime settings for {model}").format(model=model_id), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._existing = dict(options)
		self.options = dict(options)
		self._supported = set(supported)
		self._states = runtime_field_state(options, supported, provider_context=provider_context)
		outer = wx.BoxSizer(wx.VERTICAL)
		book = wx.Notebook(self)
		self._book = book
		basic = scrolledpanel.ScrolledPanel(book)
		panel = scrolledpanel.ScrolledPanel(book)
		book.AddPage(basic, _("Basic"))
		book.AddPage(panel, _("Advanced"))
		basic_helper = guiHelper.BoxSizerHelper(basic, orientation=wx.VERTICAL)
		helper = guiHelper.BoxSizerHelper(panel, orientation=wx.VERTICAL)
		helper.addItem(wx.StaticText(panel, label=_("Default uses the provider context setting where configured, otherwise the runtime default. Imported shared settings are saved separately for each model. Changes apply on the next model load and may restart the owned server.\nLower cache precision can save memory with quality tradeoffs. CPU expert placement can save GPU memory but slow generation.")))
		unavailable = [OPTION_BY_KEY[key].label for key in EDITABLE_KEYS if key not in supported]
		if unavailable:
			helper.addItem(wx.StaticText(panel, label=_("Unavailable in the installed runtime: {settings}. Update llama.cpp to use these settings.").format(settings=", ".join(unavailable))))
		self._controls = {}
		for key in EDITABLE_KEYS:
			spec = OPTION_BY_KEY[key]
			parent = basic if key in {"ctx-size", "gpu-layers"} else panel
			field_helper = basic_helper if parent is basic else helper
			label = _("Server context allocation (tokens)") if key == "ctx-size" else spec.label
			if spec.choices:
				control = field_helper.addLabeledControl(label, wx.Choice, choices=[_("Default"), *spec.choices])
				control.SetSelection(spec.choices.index(options[key]) + 1 if options.get(key) in spec.choices else 0)
			else:
				control = field_helper.addLabeledControl(label + _(" (blank = default)"), wx.TextCtrl)
				control.SetValue(options.get(key, ""))
			self._controls[key] = control
			control.Enable(key in supported)
			if key not in supported:
				control.SetHelpText(_("This setting is unavailable in the installed runtime. Update llama.cpp to use it."))
			state = self._states[key]
			field_helper.addItem(wx.StaticText(parent, label=_("Requested value for next load: {value}. Source: {source}.").format(
				value=state["effective"] or _("Runtime default"), source=_("Configuration") if state["origin"] == "configuration" else _("Provider default") if state["origin"] == "provider" else _("Runtime default"))))
			if key not in supported and key in options:
				reset_field = wx.CheckBox(parent, label=_("Remove unsupported saved setting: {setting}").format(setting=label))
				reset_field.Bind(wx.EVT_CHECKBOX, lambda event, option=key, field=control: self._clear_unsupported(option, field))
				field_helper.addItem(reset_field)
		self._kv = helper.addLabeledControl(_("KV cache placement"), wx.Choice,
			choices=[_("Default"), _("GPU"), _("CPU")])
		self._kv.SetSelection(1 if "kv-offload" in options else 2 if "no-kv-offload" in options else 0)
		self._kv.Enable({"kv-offload", "no-kv-offload"}.issubset(supported))
		self._moe = helper.addLabeledControl(_("MoE expert placement"), wx.Choice,
			choices=[_("Default"), _("All experts on CPU"), _("Experts from the first N layers on CPU")])
		self._moe.SetSelection(1 if "cpu-moe" in options else 2 if "n-cpu-moe" in options else 0)
		self._moe.Enable({"cpu-moe", "n-cpu-moe"}.issubset(supported))
		self._layers = helper.addLabeledControl(_("Number of MoE layers"), wx.TextCtrl)
		self._layers.SetValue(options.get("n-cpu-moe", ""))
		self._layers.Enable(self._moe.IsEnabled() and self._moe.GetSelection() == 2)
		self._moe.Bind(wx.EVT_CHOICE, lambda event: self._layers.Enable(self._moe.IsEnabled() and self._moe.GetSelection() == 2))
		self._extra = {}
		for key in sorted(set(OPTION_BY_KEY) - {*EDITABLE_KEYS, "cpu-moe", "n-cpu-moe", "kv-offload", "no-kv-offload"}):
			control = helper.addLabeledControl(OPTION_BY_KEY[key].label + _(" (blank removes override)"), wx.TextCtrl)
			control.SetValue(options.get(key, ""))
			control.Enable(key in supported)
			if OPTION_BY_KEY[key].choices:
				control.SetHelpText(_("Allowed values: {values}.").format(values=", ".join(OPTION_BY_KEY[key].choices)))
			self._extra[key] = control
		for key in sorted(set(options) - supported - set(EDITABLE_KEYS)):
			reset_field = wx.CheckBox(panel, label=_("Remove unsupported saved setting {setting}: {value}").format(setting=OPTION_BY_KEY[key].label, value=options[key]))
			reset_field.Bind(wx.EVT_CHECKBOX, lambda event, option=key: self._clear_other(option))
			helper.addItem(reset_field)
		basic.SetSizer(basic_helper.sizer)
		basic.SetupScrolling(scroll_x=False)
		panel.SetSizer(helper.sizer)
		panel.SetupScrolling(scroll_x=False)
		outer.Add(book, 1, wx.EXPAND | wx.ALL, 12)
		reset = wx.Button(self, label=_("Reset runtime settings to defaults"))
		reset.Bind(wx.EVT_BUTTON, self._reset)
		outer.Add(reset, 0, wx.ALL, 8)
		outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
		self.SetSizer(outer)
		self.SetSize((620, 620))
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetAffirmativeId(wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._save, id=wx.ID_OK)
		first = next((control for control in self._controls.values() if control.IsEnabled()), book)
		first.SetFocus()

	def _clear_unsupported(self, key, control):
		if OPTION_BY_KEY[key].choices:
			control.SetSelection(0)
		else:
			control.SetValue("")

	def _clear_other(self, key):
		if key in {"kv-offload", "no-kv-offload"}:
			self._kv.SetSelection(0)
		elif key in {"cpu-moe", "n-cpu-moe"}:
			self._moe.SetSelection(0)
			self._layers.SetValue("")
			self._layers.Enable(False)
		elif key in self._extra:
			self._extra[key].SetValue("")

	def _reset(self, event):
		if self._existing and wx.MessageBox(_("Reset all runtime overrides, including imported settings? Settings removed:\n{settings}").format(settings="\n".join(sorted(self._existing))),
			_("Reset runtime settings"), wx.YES_NO | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		self._existing = {}
		for control in self._extra.values():
			control.SetValue("")
		for key, control in self._controls.items():
			if OPTION_BY_KEY[key].choices:
				control.SetSelection(0)
			else:
				control.SetValue("")
		self._kv.SetSelection(0)
		self._moe.SetSelection(0)
		self._layers.SetValue("")
		self._layers.Enable(False)

	def _save(self, event):
		values = {}
		for key, control in self._controls.items():
			choices = OPTION_BY_KEY[key].choices
			index = control.GetSelection() if choices else 0
			values[key] = choices[index - 1] if choices and index > 0 else "" if choices else control.GetValue()
		try:
			existing = dict(self._existing)
			for key, control in self._extra.items():
				existing.pop(key, None)
				if control.GetValue().strip():
					existing[key] = control.GetValue().strip()
			self.options = compose_options(existing, values, self._kv.GetSelection(), self._moe.GetSelection(), self._layers.GetValue())
		except ValueError as error:
			wx.MessageBox(str(error), _("Invalid runtime setting"), wx.OK | wx.ICON_ERROR, parent=self)
			key = next((key for key in (*self._controls, *self._extra, "n-cpu-moe") if key in str(error)), None)
			control = self._layers if key == "n-cpu-moe" else self._controls.get(key) or self._extra.get(key)
			if control and control.IsEnabled():
				self._book.SetSelection(0 if key in {"ctx-size", "gpu-layers"} else 1)
				control.SetFocus()
			return
		self.EndModal(wx.ID_OK)
