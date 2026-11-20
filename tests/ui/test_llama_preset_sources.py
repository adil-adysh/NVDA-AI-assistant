from types import SimpleNamespace

import pytest

from tests.support import ADDON_ROOT, load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def dialog(monkeypatch):
	load_settings_ui(monkeypatch)
	return load_addon_module("ui.llama_preset_dialog", namespace="llama_preset_source_tests")


def test_infer_spec_type_from_cached_draft(dialog):
	assert dialog.inferred_spec_type("dflash-draft-NVFP4.gguf") == "draft-dflash"
	assert dialog.inferred_spec_type("mtp-head.gguf") == "draft-mtp"
	assert dialog.inferred_spec_type("eagle3-head.gguf") == "draft-eagle3"
	assert dialog.inferred_spec_type("dspark-head.gguf") == "draft-dspark"
	assert dialog.inferred_spec_type("model-Q4_K_M.gguf") == ""


def test_advanced_options_reject_fields_owned_by_dedicated_controls(dialog):
	for key in ("hf-repo", "hf-file", "spec-draft-hf", "spec-draft-model", "spec-type", "mmproj-auto"):
		with pytest.raises(ValueError):
			dialog._options_from_lines(f"{key} = value")


@pytest.mark.parametrize("key", ["ctx-size", "c", "gpu-layers", "ngl", "fa", "cpu-moe", "load-mode"])
def test_advanced_options_report_basic_controls_instead_of_losing_values(dialog, key):
	with pytest.raises(ValueError, match="dedicated field"):
		dialog._options_from_lines(f"{key} = value")


def test_advanced_options_reject_duplicates_and_missing_equals(dialog):
	with pytest.raises(ValueError):
		dialog._options_from_lines("ctx-size = 4096\nctx-size = 8192")
	with pytest.raises(ValueError):
		dialog._options_from_lines("ctx-size 4096")


def test_preset_id_is_stable_and_nonempty(dialog):
	assert dialog.preset_id("Unsloth Qwen 3.6") == "unsloth-qwen-3-6"
	assert dialog.preset_id("!!!") == "preset"


def test_cached_picker_accepts_selection_through_its_explicit_handler():
	source = (ADDON_ROOT / "ui" / "hf_cache_picker.py").read_text(encoding="utf-8")
	assert "self._ok.Bind(wx.EVT_BUTTON" in source
	assert "self.result = (artifact.repo, artifact.path)" in source


def test_preset_id_tracks_the_name_until_edited():
	source = (ADDON_ROOT / "ui" / "llama_preset_dialog.py").read_text(encoding="utf-8")
	assert "self._id_auto" in source
	assert "if self._id_auto:" in source


def test_missing_optional_record_fields_become_empty_text(dialog):
	record = SimpleNamespace(repo="owner/model", file="model.gguf", draft_repo=None, draft_file=None)
	assert dialog._record_text(record, "draft_repo") == ""
	assert dialog._record_text(record, "draft_file") == ""
	assert dialog._record_text(record, "repo") == "owner/model"
	assert dialog._record_text(None, "repo") == ""
