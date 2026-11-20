"""Advanced llama.cpp preset editor with manual and cached Hugging Face sources."""
from __future__ import annotations

import logging
import re

import wx
from gui import guiHelper

from ..core.hf_cache import CachedArtifact, CachedRepository, scan_cached_artifacts
from ..core.llama_options import canonical_key, validate_options, validate_repo, validate_repo_file
from ..core.llama_preset import validate_model_id, validate_preset_model
from ..core.translation import _
from ..providers.runtime.llama_models import LlamaModelRecord, build_models_preset
from .hf_cache_picker import CachedSourcePicker, format_size
from .task_runner import background_tasks

log = logging.getLogger(__name__)

BASIC_KEYS = {
	"ctx-size", "gpu-layers", "flash-attn", "cache-type-k", "cache-type-v",
	"load-mode", "cpu-moe", "n-cpu-moe", "mmproj-auto",
}
RESERVED_KEYS = {"hf-repo", "hf-file", "spec-draft-hf", "spec-draft-model", "spec-type", "mmproj-auto"}
MOE_DEFAULT, MOE_ALL, MOE_FIRST = 0, 1, 2
LOAD_MODES = ("auto", "none", "mmap", "mlock", "mmap+mlock", "dio")
SPEC_TYPES = (
	"draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark",
	"draft-dflash2", "draft-lilicorr", "ngram-simple", "ngram-map-k",
	"ngram-map-k4v", "ngram-mod", "ngram-cache",
)
MANUAL, CACHED = 0, 1


def preset_id(value):
	return re.sub(r"[\W_]+", "-", str(value).strip(), flags=re.UNICODE).strip("-").lower() or "preset"


def inferred_spec_type(path: str) -> str:
	name = path.rsplit("/", 1)[-1].lower()
	for prefix, mode in (
		("dflash-", "draft-dflash"),
		("mtp-", "draft-mtp"),
		("eagle3-", "draft-eagle3"),
		("dspark-", "draft-dspark"),
	):
		if name.startswith(prefix):
			return mode
	return ""


def _options_from_lines(text):
	options = {}
	for number, raw in enumerate(text.splitlines(), 1):
		line = raw.strip()
		if not line or line.startswith(("#", ";")):
			continue
		if "=" not in line:
			raise ValueError(_("Advanced option line {line} must be key = value.").format(line=number))
		key, value = (part.strip() for part in line.split("=", 1))
		key = canonical_key(key)
		if key in RESERVED_KEYS or key in BASIC_KEYS:
			raise ValueError(_("Use the dedicated field for {key}.").format(key=key))
		if key in options:
			raise ValueError(_("Duplicate advanced option: {key}.").format(key=key))
		options[key] = value
	return options


def _summary(repo: str, file: str) -> str:
	if not repo:
		return _("No cached selection.")
	return repo if not file else f"{repo}\n{file}"


def _record_text(record, name: str) -> str:
	if record is None:
		return ""
	return str(getattr(record, name, None) or "")


def _labeled(helper, parent, label, control_class, **kwargs):
	labeled = guiHelper.LabeledControlHelper(parent, label, control_class, **kwargs)
	helper.addItem(labeled.sizer, flag=wx.EXPAND)
	return labeled.control


def _labeled_multiline(helper, parent, label, control_class=wx.TextCtrl, *, proportion=0, **kwargs):
	label_control = wx.StaticText(parent, label=label)
	control = control_class(parent, **kwargs)
	sizer = wx.BoxSizer(wx.VERTICAL)
	sizer.Add(label_control)
	sizer.AddSpacer(4)
	sizer.Add(control, 1 if proportion else 0, wx.EXPAND)
	helper.addItem(sizer, flag=wx.EXPAND, proportion=proportion)
	return control


class LlamaPresetDialog(wx.Dialog):
	def __init__(self, parent, provider, record=None):
		title = _("Edit llama.cpp preset") if record else _("New llama.cpp preset")
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._provider = provider
		self._record = record
		self._closed = False
		self._cache_task = None
		self._cache_repos: tuple[CachedRepository, ...] = ()
		self._cache_scanned = False
		self._setting_spec = False
		self._setting_id = False
		self._id_auto = not record
		self._spec_type_auto = bool(record.spec_type_auto) if record else False
		self._manual_main = _record_text(record, "repo")
		self._cached_main_repo = _record_text(record, "repo") if record and record.file else ""
		self._cached_main_file = _record_text(record, "file")
		self._manual_draft = _record_text(record, "draft_repo")
		self._cached_draft_repo = _record_text(record, "draft_repo") if record and record.draft_file else ""
		self._cached_draft_file = _record_text(record, "draft_file")
		self._main_mode = CACHED if record and record.file else MANUAL
		self._draft_mode = CACHED if record and record.draft_file else MANUAL
		self._draft_enabled = bool(record and (record.draft_repo or record.draft_file))
		self._problem_targets = []
		self._build_ui(record)
		self._scan_cache()
		self._update_main_summary()
		self._update_draft_summary()
		self._toggle_main_mode(focus=False)
		self._toggle_draft_mode(focus=False)
		self._toggle_draft(focus=False)
		self._update_preview()
		self._name.SetFocus()

	def _build_ui(self, record) -> None:
		root = wx.BoxSizer(wx.VERTICAL)
		identity = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._name = _labeled(identity, self, _("&Preset name:"), wx.TextCtrl)
		self._name.SetValue(record.display_name if record else "")
		self._id = _labeled(identity, self, _("Preset &ID:"), wx.TextCtrl)
		self._id.SetValue(record.model_id if record else "")
		if record:
			self._id.Enable(False)
		identity.addItem(wx.StaticText(self, label=_(
			"The ID is sent to llama-server and cannot be changed after saving.")))
		root.Add(identity.sizer, 0, wx.EXPAND | wx.ALL, 10)
		self._name.Bind(wx.EVT_TEXT, self._name_changed)
		self._id.Bind(wx.EVT_TEXT, self._id_changed)

		self._tabs = wx.Notebook(self)
		self._build_model_page()
		self._build_runtime_page()
		self._build_preview_page()
		root.Add(self._tabs, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

		self._problems_label = wx.StaticText(self, label=_("Problems"))
		self._problems = wx.ListBox(self)
		self._problems.SetName(_("Problems"))
		self._problems.Bind(wx.EVT_LISTBOX_DCLICK, lambda event: self._go_to_problem())
		self._problem_go = wx.Button(self, label=_("Go to problem"))
		self._problem_go.Bind(wx.EVT_BUTTON, lambda event: self._go_to_problem())
		root.Add(self._problems_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
		problem_row = wx.BoxSizer(wx.HORIZONTAL)
		problem_row.Add(self._problems, 1, wx.EXPAND)
		problem_row.Add(self._problem_go, 0, wx.LEFT, 6)
		root.Add(problem_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
		self._problems_label.Hide()
		self._problems.Hide()
		self._problem_go.Hide()

		self._status = wx.StaticText(self, label=_("Ready."))
		self._status.SetName(_("Status"))
		root.Add(self._status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		buttons.AddStretchSpacer()
		self._ok_button = wx.Button(self, id=wx.ID_OK, label=_("&OK"))
		self._ok_button.Bind(wx.EVT_BUTTON, self._on_ok)
		buttons.Add(self._ok_button, 0, wx.RIGHT, 6)
		close = wx.Button(self, id=wx.ID_CANCEL, label=_("&Close"))
		buttons.Add(close)
		root.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

		for control in (self._name, self._id, self._main_manual, self._draft_manual,
				self._main_cached_summary, self._draft_cached_summary, self._projector_info):
			control.SetMinSize((620, -1))
		self._advanced.SetMinSize((720, 180))
		self._preview.SetMinSize((720, 380))

		self.SetSizer(root)
		self.SetSize((940, 900))
		self.SetMinSize((820, 680))
		self._centre_on_screen()
		wx.CallAfter(self._centre_on_screen)
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetAffirmativeId(wx.ID_OK)
		self.Bind(wx.EVT_CLOSE, self._close)

	def _centre_on_screen(self) -> None:
		self.Layout()
		area = wx.Display().GetClientArea()
		size = self.GetSize()
		self.SetPosition((
			area.x + max(0, (area.width - size.width) // 2),
			area.y + max(0, (area.height - size.height) // 2),
		))

	def _build_model_page(self) -> None:
		page = wx.ScrolledWindow(self._tabs, style=wx.VSCROLL | wx.BORDER_NONE)
		page.SetScrollRate(0, 16)
		page_sizer = wx.BoxSizer(wx.VERTICAL)

		main_box = wx.StaticBoxSizer(wx.VERTICAL, page, _("Main model source"))
		main_parent = main_box.GetStaticBox()
		self._main_mode_box = wx.RadioBox(main_parent, label=_("Input method"),
			choices=[_("Manual Hugging Face reference"), _("Cached model")],
			majorDimension=1, style=wx.RA_SPECIFY_ROWS)
		self._main_mode_box.SetSelection(self._main_mode)
		self._main_mode_box.Bind(wx.EVT_RADIOBOX, lambda event: self._on_main_mode())
		main_box.Add(self._main_mode_box, 0, wx.EXPAND | wx.ALL, 6)

		self._main_manual_panel = wx.Panel(main_parent)
		manual_helper = guiHelper.BoxSizerHelper(self._main_manual_panel, orientation=wx.VERTICAL)
		self._main_manual = _labeled(manual_helper, self._main_manual_panel,
			_("Hugging Face &reference:"), wx.TextCtrl)
		self._main_manual.SetValue(self._manual_main)
		self._main_manual.Bind(wx.EVT_TEXT, self._on_manual_main)
		self._main_manual.Bind(wx.EVT_KILL_FOCUS, lambda event: self._update_projector_info())
		manual_helper.addItem(wx.StaticText(self._main_manual_panel,
			label=_("owner/repository or owner/repository:quant")))
		manual_helper.addItem(wx.StaticText(self._main_manual_panel, label=_(
			"Manual references are passed to llama.cpp unchanged. Leave the quant off to let llama.cpp choose.")))
		self._main_manual_panel.SetSizer(manual_helper.sizer)
		main_box.Add(self._main_manual_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

		self._main_cached_panel = wx.Panel(main_parent)
		cached_helper = guiHelper.BoxSizerHelper(self._main_cached_panel, orientation=wx.VERTICAL)
		self._main_cached_summary = _labeled_multiline(cached_helper, self._main_cached_panel,
			_("Selected cached &model:"), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 46))
		main_buttons = wx.BoxSizer(wx.HORIZONTAL)
		choose_main = wx.Button(self._main_cached_panel, label=_("&Choose cached model..."))
		choose_main.Bind(wx.EVT_BUTTON, self._choose_main)
		self._choose_main_button = choose_main
		main_buttons.Add(choose_main, 0, wx.RIGHT, 6)
		clear_main = wx.Button(self._main_cached_panel, label=_("Clear"))
		clear_main.Bind(wx.EVT_BUTTON, self._clear_main)
		main_buttons.Add(clear_main)
		cached_helper.addItem(main_buttons)
		cached_helper.addItem(wx.StaticText(self._main_cached_panel, label=_(
			"Only the repository and exact filename are stored. No local path or commit is saved.")))
		self._main_cached_panel.SetSizer(cached_helper.sizer)
		main_box.Add(self._main_cached_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
		page_sizer.Add(main_box, 0, wx.EXPAND | wx.ALL, 4)

		draft_box = wx.StaticBoxSizer(wx.VERTICAL, page, _("Draft model (optional)"))
		draft_parent = draft_box.GetStaticBox()
		self._draft_check = wx.CheckBox(draft_parent, label=_("Use a separate draft model"))
		self._draft_check.SetValue(self._draft_enabled)
		self._draft_check.Bind(wx.EVT_CHECKBOX, lambda event: self._toggle_draft())
		draft_box.Add(self._draft_check, 0, wx.ALL, 6)
		self._draft_body = wx.Panel(draft_parent)
		body_helper = guiHelper.BoxSizerHelper(self._draft_body, orientation=wx.VERTICAL)
		self._draft_mode_box = wx.RadioBox(self._draft_body, label=_("Input method"),
			choices=[_("Manual Hugging Face reference"), _("Cached model")],
			majorDimension=1, style=wx.RA_SPECIFY_ROWS)
		self._draft_mode_box.SetSelection(self._draft_mode)
		self._draft_mode_box.Bind(wx.EVT_RADIOBOX, lambda event: self._on_draft_mode())
		body_helper.addItem(self._draft_mode_box, flag=wx.EXPAND | wx.ALL, border=4)

		self._draft_manual_panel = wx.Panel(self._draft_body)
		draft_manual_helper = guiHelper.BoxSizerHelper(self._draft_manual_panel, orientation=wx.VERTICAL)
		self._draft_manual = _labeled(draft_manual_helper, self._draft_manual_panel,
			_("Hugging Face &reference:"), wx.TextCtrl)
		self._draft_manual.SetValue(self._manual_draft)
		self._draft_manual.Bind(wx.EVT_TEXT, self._on_manual_draft)
		draft_manual_helper.addItem(wx.StaticText(self._draft_manual_panel,
			label=_("owner/repository or owner/repository:quant")))
		self._draft_manual_panel.SetSizer(draft_manual_helper.sizer)
		body_helper.addItem(self._draft_manual_panel, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

		self._draft_cached_panel = wx.Panel(self._draft_body)
		draft_cached_helper = guiHelper.BoxSizerHelper(self._draft_cached_panel, orientation=wx.VERTICAL)
		self._draft_cached_summary = _labeled_multiline(draft_cached_helper, self._draft_cached_panel,
			_("Selected cached &draft:"), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 46))
		draft_buttons = wx.BoxSizer(wx.HORIZONTAL)
		choose_draft = wx.Button(self._draft_cached_panel, label=_("Choose cached &draft..."))
		choose_draft.Bind(wx.EVT_BUTTON, self._choose_draft)
		self._choose_draft_button = choose_draft
		draft_buttons.Add(choose_draft, 0, wx.RIGHT, 6)
		clear_draft = wx.Button(self._draft_cached_panel, label=_("Clear"))
		clear_draft.Bind(wx.EVT_BUTTON, self._clear_draft)
		draft_buttons.Add(clear_draft)
		draft_cached_helper.addItem(draft_buttons)
		self._draft_cached_panel.SetSizer(draft_cached_helper.sizer)
		body_helper.addItem(self._draft_cached_panel, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

		self._spec_type = _labeled(body_helper, self._draft_body,
			_("Speculative &mode:"), wx.ComboBox, choices=list(SPEC_TYPES))
		if self._record:
			self._spec_type.SetValue(self._record.preset_options.get("spec-type", ""))
		self._spec_type.Bind(wx.EVT_TEXT, self._on_spec_type)
		self._spec_type.Bind(wx.EVT_COMBOBOX, self._on_spec_type)
		body_helper.addItem(wx.StaticText(self._draft_body, label=_(
			"Leave blank to let llama.cpp infer the mode. An exact cached draft file needs a draft-* mode.")))
		self._draft_body.SetSizer(body_helper.sizer)
		draft_box.Add(self._draft_body, 0, wx.EXPAND)
		page_sizer.Add(draft_box, 0, wx.EXPAND | wx.ALL, 4)

		projector_box = wx.StaticBoxSizer(wx.VERTICAL, page, _("Projector (optional)"))
		projector_parent = projector_box.GetStaticBox()
		projector_helper = guiHelper.BoxSizerHelper(page, sizer=projector_box)
		self._projector_choice = wx.RadioBox(projector_parent, label=_("Projector mode"),
			choices=[_("Automatic (same repository)"), _("Disabled")],
			majorDimension=2, style=wx.RA_SPECIFY_COLS)
		if (self._record.preset_options.get("mmproj-auto") if self._record else None) in {"false", "0", "no"}:
			self._projector_choice.SetSelection(1)
		self._projector_choice.Bind(wx.EVT_RADIOBOX, lambda event: self._on_change())
		projector_helper.addItem(self._projector_choice, flag=wx.EXPAND | wx.ALL, border=6)
		self._projector_info = _labeled_multiline(projector_helper, projector_parent,
			_("Cached &projectors:"), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 58))
		projector_helper.addItem(wx.StaticText(projector_parent, label=_(
			"llama.cpp chooses one projector from the model repository. Cross-repository projectors are not supported.")))
		page_sizer.Add(projector_box, 0, wx.EXPAND | wx.ALL, 4)

		page.SetSizer(page_sizer)
		page.FitInside()
		page.Bind(wx.EVT_SIZE, lambda event: (event.Skip(), page.FitInside()))
		self._tabs.AddPage(page, _("Model"))
		self._model_page = page

	def _build_runtime_page(self) -> None:
		page = wx.Panel(self._tabs)
		page_sizer = wx.BoxSizer(wx.VERTICAL)
		options = dict(self._record.preset_options) if self._record else {}
		columns = wx.BoxSizer(wx.HORIZONTAL)
		left = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
		right = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)

		self._ctx = _labeled(left, page, _("&Context length:"), wx.SpinCtrl, min=0, max=1048576)
		self._ctx.SetValue(int(options.get("ctx-size", 0) or 0))
		self._layers = _labeled(right, page, _("&GPU layers:"), wx.TextCtrl)
		self._layers.SetValue(options.get("gpu-layers", "auto"))

		self._fa = _labeled(left, page, _("&Flash Attention:"), wx.Choice,
			choices=[_("Default"), "auto", "on", "off"])
		self._fa.SetSelection((["auto", "on", "off"].index(options["flash-attn"]) + 1)
			if options.get("flash-attn") in {"auto", "on", "off"} else 0)
		self._kv = _labeled(right, page, _("&KV cache precision:"), wx.Choice,
			choices=[_("Default"), "f16", "bf16", "q8_0", "q4_0"])
		self._kv.SetSelection((["f16", "bf16", "q8_0", "q4_0"].index(options["cache-type-k"]) + 1)
			if options.get("cache-type-k") in {"f16", "bf16", "q8_0", "q4_0"} else 0)

		self._load_mode = _labeled(left, page, _("&Model loading mode:"), wx.Choice,
			choices=[_("Default"), *LOAD_MODES])
		self._load_mode.SetSelection((list(LOAD_MODES).index(options["load-mode"]) + 1)
			if options.get("load-mode") in LOAD_MODES else 0)
		self._moe = _labeled(right, page, _("&MoE expert placement:"), wx.Choice, choices=[
			_("Default"), _("All experts on CPU"), _("First N layers on CPU")])
		self._moe.SetSelection(1 if options.get("cpu-moe") == "true" else (2 if "n-cpu-moe" in options else 0))

		self._moe_layers = _labeled(right, page, _("MoE &layers on CPU:"), wx.SpinCtrl, min=0, max=999)
		self._moe_layers.SetValue(int(options.get("n-cpu-moe", 0) or 0))

		columns.Add(left.sizer, 1, wx.EXPAND | wx.RIGHT, 18)
		columns.Add(right.sizer, 1, wx.EXPAND)
		page_sizer.Add(columns, 0, wx.EXPAND | wx.ALL, 12)
		reset = wx.Button(page, label=_("Reset runtime settings"))
		reset.Bind(wx.EVT_BUTTON, self._reset_runtime)
		page_sizer.Add(reset, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

		advanced_helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
		self._advanced = _labeled_multiline(advanced_helper, page,
			_("Additional per-model &options:"), style=wx.TE_MULTILINE,
			size=(-1, 180), proportion=1)
		extra = {key: value for key, value in options.items() if key not in BASIC_KEYS and key != "spec-type"}
		self._advanced.SetValue("\n".join(f"{key} = {value}" for key, value in sorted(extra.items())))
		self._advanced.Bind(wx.EVT_TEXT, lambda event: self._update_preview())
		advanced_helper.addItem(wx.StaticText(page, label=_(
			"Only per-model llama.cpp options. Source fields, spec-type and mmproj-auto have dedicated controls.")))
		page_sizer.Add(advanced_helper.sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		page.SetSizer(page_sizer)
		self._tabs.AddPage(page, _("Runtime"))
		self._runtime_page = page

	def _build_preview_page(self) -> None:
		page = wx.Panel(self._tabs)
		helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
		self._preview = _labeled_multiline(helper, page,
			_("Generated preset &preview:"), style=wx.TE_READONLY | wx.TE_MULTILINE,
			size=(-1, 380), proportion=1)
		row = wx.BoxSizer(wx.HORIZONTAL)
		copy = wx.Button(page, label=_("Copy preview"))
		copy.Bind(wx.EVT_BUTTON, self._copy_preview)
		row.Add(copy)
		row.AddStretchSpacer()
		self._preview_status = wx.StaticText(page, label="")
		row.Add(self._preview_status, 0, wx.ALIGN_CENTER_VERTICAL)
		helper.addItem(row, flag=wx.EXPAND)
		page.SetSizer(helper.sizer)
		self._tabs.AddPage(page, _("Preview"))
		self._preview_page = page

	def _close(self, event) -> None:
		self._closed = True
		if self._cache_task is not None:
			self._cache_task.cancel()
			self._cache_task = None
		self.Destroy()

	def _name_changed(self, event) -> None:
		if self._id_auto:
			self._setting_id = True
			try:
				self._id.SetValue(preset_id(self._name.GetValue()))
			finally:
				self._setting_id = False
		self._update_preview()

	def _id_changed(self, event) -> None:
		if not self._setting_id:
			self._id_auto = False
		self._update_preview()

	def _on_manual_main(self, event) -> None:
		self._manual_main = self._main_manual.GetValue()
		self._update_preview()

	def _on_manual_draft(self, event) -> None:
		self._manual_draft = self._draft_manual.GetValue()
		self._update_preview()

	def _on_main_mode(self) -> None:
		self._main_mode = self._main_mode_box.GetSelection()
		self._toggle_main_mode()
		if self._main_mode == CACHED and not self._cached_main_file:
			self._status.SetLabel(_("Cached model mode. Choose a cached repository and file."))
		else:
			self._status.SetLabel(_("Ready."))
		self._update_preview()

	def _toggle_main_mode(self, focus: bool = True) -> None:
		manual = self._main_mode == MANUAL
		self._main_manual_panel.Show(manual)
		self._main_cached_panel.Show(not manual)
		self._model_page.Layout()
		self._model_page.FitInside()
		if not focus:
			return
		control = self._main_manual if manual else self._choose_main_button
		if control is not None:
			wx.CallAfter(control.SetFocus)

	def _on_draft_mode(self) -> None:
		self._draft_mode = self._draft_mode_box.GetSelection()
		self._toggle_draft_mode()
		self._update_preview()

	def _toggle_draft_mode(self, focus: bool = True) -> None:
		manual = self._draft_mode == MANUAL
		self._draft_manual_panel.Show(manual)
		self._draft_cached_panel.Show(not manual)
		self._draft_body.Layout()
		self._model_page.FitInside()
		if focus and self._draft_check.GetValue():
			control = self._draft_manual if manual else self._draft_cached_summary
			wx.CallAfter(control.SetFocus)

	def _toggle_draft(self, focus: bool = True) -> None:
		self._draft_enabled = self._draft_check.GetValue()
		self._draft_body.Enable(self._draft_enabled)
		if not self._draft_enabled and self._spec_type_auto:
			self._set_spec_type("", auto=False)
		if self._draft_enabled and not self._spec_type.GetValue().strip() and self._cached_draft_file:
			inferred = inferred_spec_type(self._cached_draft_file)
			if inferred:
				self._set_spec_type(inferred, auto=True)
		self._update_preview()

	def _set_spec_type(self, value: str, *, auto: bool = False) -> None:
		self._setting_spec = True
		try:
			self._spec_type.SetValue(value)
		finally:
			self._setting_spec = False
		self._spec_type_auto = bool(auto)

	def _on_spec_type(self, event) -> None:
		if not self._setting_spec:
			self._spec_type_auto = False
		self._update_preview()

	def _update_main_summary(self) -> None:
		self._main_cached_summary.SetValue(_summary(self._cached_main_repo, self._cached_main_file))

	def _update_draft_summary(self) -> None:
		self._draft_cached_summary.SetValue(_summary(self._cached_draft_repo, self._cached_draft_file))

	def _choose_main(self, event) -> None:
		picker = CachedSourcePicker(self, kind="main", initial_repo=self._cached_main_repo,
			initial_file=self._cached_main_file)
		try:
			if picker.ShowModal() == wx.ID_OK and picker.result:
				self._cached_main_repo, self._cached_main_file = picker.result
				self._manual_main = self._cached_main_repo
				self._main_mode = CACHED
				self._main_mode_box.SetSelection(CACHED)
				self._toggle_main_mode()
				self._update_main_summary()
				self._status.SetLabel(_("Cached model selected."))
				self._update_projector_info()
				self._update_preview()
		finally:
			picker.Destroy()

	def _clear_main(self, event) -> None:
		self._cached_main_repo = ""
		self._cached_main_file = ""
		self._update_main_summary()
		self._update_projector_info()
		self._update_preview()

	def _choose_draft(self, event) -> None:
		picker = CachedSourcePicker(self, kind="draft", initial_repo=self._cached_draft_repo,
			initial_file=self._cached_draft_file)
		try:
			if picker.ShowModal() == wx.ID_OK and picker.result:
				self._cached_draft_repo, self._cached_draft_file = picker.result
				self._manual_draft = self._cached_draft_repo
				self._draft_mode = CACHED
				self._draft_mode_box.SetSelection(CACHED)
				self._draft_check.SetValue(True)
				self._toggle_draft_mode()
				self._toggle_draft()
				self._update_draft_summary()
				inferred = inferred_spec_type(self._cached_draft_file)
				if inferred and (not self._spec_type.GetValue().strip() or self._spec_type_auto):
					self._set_spec_type(inferred, auto=True)
				self._status.SetLabel(_("Cached draft selected."))
				self._update_preview()
		finally:
			picker.Destroy()

	def _clear_draft(self, event) -> None:
		self._cached_draft_repo = ""
		self._cached_draft_file = ""
		self._update_draft_summary()
		self._update_preview()

	def _scan_cache(self) -> None:
		if self._cache_task is not None:
			return
		self._projector_info.SetValue(_("Scanning Hugging Face cache..."))
		def work(cancel):
			return scan_cached_artifacts(cancelled=cancel.is_set)
		def done(repositories):
			if self._closed:
				return
			self._cache_repos = tuple(repositories)
			self._cache_scanned = True
			self._update_projector_info()
		def failed(error):
			if self._closed:
				return
			self._cache_scanned = True
			self._projector_info.SetValue(str(error))
		def finished():
			self._cache_task = None
		self._cache_task = background_tasks.submit(work, on_success=done, on_error=failed,
			on_finally=finished, is_alive=lambda: not self._closed,
			task_name="scan hugging face cache")

	def _projector_repo(self) -> str:
		if self._main_mode == CACHED:
			return self._cached_main_repo
		return self._manual_main.split(":", 1)[0].strip()

	def _update_projector_info(self) -> None:
		if not self._cache_scanned:
			self._projector_info.SetValue(_("Scanning Hugging Face cache..."))
			return
		repo = self._projector_repo()
		if not repo:
			self._projector_info.SetValue(_("Choose a main model to inspect cached projectors."))
			return
		cached = next((item for item in self._cache_repos if item.repo.casefold() == repo.casefold()), None)
		if cached is None:
			self._projector_info.SetValue(_(
				"This repository is not currently cached. Automatic selection resolves when the model loads."))
			return
		projectors = [item for item in cached.artifacts if item.role == "projector"]
		if not projectors:
			self._projector_info.SetValue(_(
				"No projector is cached for this repository. Automatic mode uses one if the repository publishes it."))
			return
		lines = [_("Cached projectors in this repository:")]
		lines.extend(f"  {item.path} - {format_size(item.size)}" for item in projectors)
		lines.append(_("llama.cpp chooses one automatically; this list is informational."))
		self._projector_info.SetValue("\n".join(lines))

	def _options(self) -> dict[str, str]:
		options = _options_from_lines(self._advanced.GetValue())
		for key in BASIC_KEYS:
			options.pop(key, None)
		if self._ctx.GetValue() > 0:
			options["ctx-size"] = str(self._ctx.GetValue())
		layers = self._layers.GetValue().strip()
		if layers:
			options["gpu-layers"] = layers
		if self._fa.GetSelection() > 0:
			options["flash-attn"] = self._fa.GetStringSelection()
		if self._kv.GetSelection() > 0:
			options["cache-type-k"] = self._kv.GetStringSelection()
			options["cache-type-v"] = self._kv.GetStringSelection()
		if self._load_mode.GetSelection() > 0:
			options["load-mode"] = self._load_mode.GetStringSelection()
		selection = self._moe.GetSelection()
		options.pop("cpu-moe", None)
		options.pop("n-cpu-moe", None)
		if selection == 1:
			options["cpu-moe"] = "true"
		elif selection == 2:
			options["n-cpu-moe"] = str(self._moe_layers.GetValue())
		spec_type = self._spec_type.GetValue().strip()
		if spec_type:
			options["spec-type"] = spec_type
		if self._projector_choice.GetSelection() == 1:
			options["mmproj-auto"] = "false"
		return validate_options(options)

	def _source(self) -> dict[str, str | None]:
		if self._main_mode == MANUAL:
			repo, file_name = self._manual_main.strip(), None
		else:
			repo, file_name = self._cached_main_repo, self._cached_main_file or None
		draft = self._draft_check.GetValue()
		if not draft:
			draft_repo = draft_file = None
		elif self._draft_mode == MANUAL:
			draft_repo, draft_file = self._manual_draft.strip(), None
		else:
			draft_repo, draft_file = self._cached_draft_repo, self._cached_draft_file or None
		return {
			"repo": repo,
			"file": file_name,
			"draft_repo": draft_repo,
			"draft_file": draft_file,
		}

	def _current_record(self) -> LlamaModelRecord:
		source = self._source()
		return LlamaModelRecord(
			self._id.GetValue().strip() or preset_id(self._name.GetValue()),
			source["repo"] or "owner/model",
			file=source["file"],
			draft_repo=source["draft_repo"],
			draft_file=source["draft_file"],
			preset_options=self._options(),
			display_name=self._name.GetValue().strip(),
			spec_type_auto=self._spec_type_auto,
		)

	def _update_preview(self) -> None:
		source = self._source()
		if not str(source["repo"] or "").strip():
			self._preview.SetValue(_("Preview unavailable.\n\nEnter a main model reference or choose a cached model."))
			self._preview_status.SetLabel(_("Needs attention"))
			return
		try:
			record = self._current_record()
			text = build_models_preset([record])
			self._preview.SetValue(text)
			self._preview_status.SetLabel(_("Valid"))
		except Exception as error:
			self._preview.SetValue(_("Preview unavailable.\n\n{error}").format(error=error))
			self._preview_status.SetLabel(_("Needs attention"))

	def _copy_preview(self, event) -> None:
		text = self._preview.GetValue()
		if not text:
			return
		if wx.TheClipboard.Open():
			try:
				wx.TheClipboard.SetData(wx.TextDataObject(text))
			finally:
				wx.TheClipboard.Close()
			self._status.SetLabel(_("Preset preview copied."))

	def _reset_runtime(self, event) -> None:
		self._ctx.SetValue(0)
		self._layers.SetValue("auto")
		self._fa.SetSelection(0)
		self._kv.SetSelection(0)
		self._load_mode.SetSelection(0)
		self._moe.SetSelection(0)
		self._moe_layers.SetValue(0)
		self._advanced.SetValue("")
		self._update_preview()

	def _on_change(self) -> None:
		self._update_preview()

	def _problems_for(self):
		problems = []
		if not self._name.GetValue().strip():
			problems.append((_("Preset name is required."), lambda: self._name.SetFocus()))
		try:
			validate_model_id(self._id.GetValue().strip())
		except ValueError as error:
			problems.append((str(error), lambda: self._id.SetFocus()))
		source = self._source()
		try:
			repo = validate_repo(source["repo"] or "")
			if not repo:
				raise ValueError(_("Enter a main model reference or choose a cached model."))
			if self._main_mode == CACHED:
				if ":" in repo:
					raise ValueError(_("A cached repository must not include :quant. Select an exact file instead."))
				if not source["file"]:
					raise ValueError(_("Choose a cached file, or switch to manual reference."))
				validate_repo_file(source["file"])
		except ValueError as error:
			problems.append((_("Main model: {error}").format(error=error),
				lambda: self._goto_main()))
		if source["draft_repo"] is not None:
			try:
				draft_repo = validate_repo(source["draft_repo"])
				if self._draft_mode == CACHED:
					if ":" in draft_repo:
						raise ValueError(_("A cached repository must not include :quant. Select an exact file instead."))
					if not source["draft_file"]:
						raise ValueError(_("Choose a cached draft file, or switch to manual reference."))
					validate_repo_file(source["draft_file"])
			except ValueError as error:
				problems.append((_("Draft model: {error}").format(error=error),
					lambda: self._goto_draft()))
		try:
			options = self._options()
			if source["draft_file"] and not options.get("spec-type"):
				raise ValueError(_("An exact cached draft file needs a speculative mode."))
		except ValueError as error:
			problems.append((_("Draft model: {error}").format(error=error),
				lambda: self._goto_draft_spec()))
		try:
			if not problems:
				validate_preset_model(self._id.GetValue().strip(), source["repo"], source["file"],
					source["draft_repo"], source["draft_file"], self._options())
		except ValueError as error:
			problems.append((str(error), lambda: self._goto_main()))
		if self._main_mode == CACHED and self._cache_scanned:
			artifact = self._find_cached(self._cached_main_repo, self._cached_main_file)
			if artifact is not None and not artifact.complete:
				problems.append((_("Main model: the cached file is an incomplete split."),
					lambda: self._choose_main(None)))
		if self._draft_enabled and self._draft_mode == CACHED and self._cache_scanned:
			artifact = self._find_cached(self._cached_draft_repo, self._cached_draft_file)
			if artifact is not None and not artifact.complete:
				problems.append((_("Draft model: the cached file is an incomplete split."),
					lambda: self._choose_draft(None)))
		return problems

	def _find_cached(self, repo: str, path: str) -> CachedArtifact | None:
		for cached in self._cache_repos:
			if cached.repo.casefold() != repo.casefold():
				continue
			return next((item for item in cached.artifacts if item.path == path), None)
		return None

	def _goto_main(self):
		self._tabs.SetSelection(0)
		control = self._main_manual if self._main_mode == MANUAL else self._cached_main_summary
		wx.CallAfter(control.SetFocus)

	def _goto_draft(self):
		self._tabs.SetSelection(0)
		control = self._draft_manual if self._draft_mode == MANUAL else self._cached_draft_summary
		wx.CallAfter(control.SetFocus)

	def _goto_draft_spec(self):
		self._tabs.SetSelection(0)
		wx.CallAfter(self._spec_type.SetFocus)

	def _show_problems(self, problems) -> None:
		self._problem_targets = [target for _, target in problems]
		self._problems.Set([message for message, _ in problems])
		self._problems_label.SetLabel(_("Problems ({count})").format(count=len(problems)))
		self._problems_label.Show()
		self._problems.Show()
		self._problem_go.Show()
		self.Layout()
		self._problems.SetFocus()

	def _hide_problems(self) -> None:
		self._problem_targets = []
		self._problems_label.Hide()
		self._problems.Hide()
		self._problem_go.Hide()
		self.Layout()

	def _go_to_problem(self) -> None:
		index = self._problems.GetSelection()
		if 0 <= index < len(self._problem_targets):
			self._problem_targets[index]()

	def _on_ok(self, event) -> None:
		source = self._source()
		log.debug("Saving llama.cpp preset source=%r main_mode=%r cached=%r/%r",
			source, self._main_mode, self._cached_main_repo, self._cached_main_file)
		problems = self._problems_for()
		if problems:
			self._show_problems(problems)
			self._status.SetLabel(_("{count} problem(s). Fix them before saving.").format(count=len(problems)))
			return
		self._hide_problems()
		source = self._source()
		options = self._options()
		try:
			model_id = self._id.GetValue().strip()
			name = self._name.GetValue().strip() or model_id
			if self._record:
				self._provider.update_preset(model_id, repo=source["repo"], file=source["file"],
					draft_repo=source["draft_repo"], draft_file=source["draft_file"],
					display_name=name, options=options, spec_type_auto=self._spec_type_auto)
			else:
				self._provider.create_preset(source["repo"], model_id, name,
					file=source["file"], draft_repo=source["draft_repo"],
					draft_file=source["draft_file"], options=options,
					spec_type_auto=self._spec_type_auto, select=True)
		except Exception as error:
			wx.MessageBox(str(error), _("Unable to save preset"), wx.OK | wx.ICON_ERROR, parent=self)
			return
		self.EndModal(wx.ID_OK)
