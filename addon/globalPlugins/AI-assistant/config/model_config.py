# -*- coding: utf-8 -*-
"""Per-model sampling configuration.

Each model can pin its own generation parameters — context window,
temperature, top-k, top-p, max tokens, and repetition penalty.  Values
are persisted per ``(provider_id, model_id)`` in a JSON file next to
the enabled-models store and resolved at request time by the provider
adapter: an explicitly pinned value wins, otherwise the provider's
global setting is used.

Model configuration follows the same pattern as provider configuration:

- The model Configure dialog is generic and data-driven — the fields
  come from :data:`MODEL_CONFIG_FIELDS`, never from provider-ID
  branches.
- Only *sampling* fields live here.  Model availability, download,
  and active-model selection belong to the model manager.
- ``top_k`` and ``repeat_penalty`` are pinned-only fields: they are
  sent on the wire only when a model explicitly configures them,
  because OpenAI-compatible cloud endpoints reject unknown parameters.
  (Historically these fields were exposed globally but never sent.)
"""

from __future__ import annotations

import builtins
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from . import defaults


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


def _store_path() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "model_configs.json"


@dataclass(frozen=True)
class ModelSamplingConfig:
	"""Sampling parameters for a single model.

	Every field is optional: ``None`` means *not pinned* — fall back to
	the provider's global setting (or the static default).
	"""

	num_ctx: int | None = None
	temperature: float | None = None
	top_k: int | None = None
	top_p: float | None = None
	max_tokens: int | None = None
	repeat_penalty: float | None = None


#: Fields resolved as *explicit override → provider global setting*.
#: These are always sent (as today) — the model value just wins.
_WIRE_FALLBACK_FIELDS: tuple[str, ...] = ("temperature", "top_p", "max_tokens")

#: Fields that fall back to the provider global for *local* backends
#: (Ollama, LiteRT-LM) but are suppressed for cloud providers (Gemini,
#: OpenAI) unless a model pins them explicitly.  Cloud endpoints reject
#: non-standard request parameters with HTTP 400.
_LOCAL_FALLBACK_FIELDS: tuple[str, ...] = ("num_ctx",)

#: Fields sent only when a model pins them explicitly.  OpenAI-compatible
#: cloud endpoints reject unknown request parameters, so these must never
#: leak onto the wire from a global default.
_PINNED_ONLY_FIELDS: tuple[str, ...] = ("top_k", "repeat_penalty")

#: All user-configurable sampling field IDs, in dialog order.
SAMPLING_FIELD_IDS: tuple[str, ...] = (
	_WIRE_FALLBACK_FIELDS + _LOCAL_FALLBACK_FIELDS + _PINNED_ONLY_FIELDS
)


@dataclass(frozen=True)
class ModelFieldSpec:
	"""A single sampling field shown in the model Configure dialog.

	``id`` maps onto a :class:`ModelSamplingConfig` attribute.  The spec
	is provider-agnostic — every provider's models expose the same
	sampling fields.
	"""

	id: str
	# TRANSLATORS: Field label in a model Configure dialog (subclassed per field).
	label: str
	kind: Literal["int", "float"] = "int"
	minimum: float | None = None
	default: float | None = None


#: Sampling fields offered by every model Configure dialog.
MODEL_CONFIG_FIELDS: tuple[ModelFieldSpec, ...] = (
	ModelFieldSpec(
		"num_ctx",
		_("Context window size:"),
		kind="int",
		minimum=256,
		default=defaults.DEFAULT_NUM_CTX,
	),
	ModelFieldSpec(
		"temperature",
		_("Temperature:"),
		kind="float",
		minimum=0.0,
		default=defaults.DEFAULT_GENERATE_TEMPERATURE,
	),
	ModelFieldSpec(
		"top_k",
		_("Top-k:"),
		kind="int",
		minimum=0,
		default=defaults.DEFAULT_GENERATE_TOP_K,
	),
	ModelFieldSpec(
		"top_p",
		_("Top-p:"),
		kind="float",
		minimum=0.0,
		default=defaults.DEFAULT_GENERATE_TOP_P,
	),
	ModelFieldSpec(
		"max_tokens",
		_("Max tokens:"),
		kind="int",
		minimum=1,
		default=defaults.DEFAULT_GENERATE_MAX_TOKENS,
	),
	ModelFieldSpec(
		"repeat_penalty",
		_("Repetition penalty:"),
		kind="float",
		minimum=0.0,
		default=defaults.DEFAULT_GENERATE_PRESENCE_PENALTY,
	),
)

MODEL_FIELD_BY_ID: dict[str, ModelFieldSpec] = {spec.id: spec for spec in MODEL_CONFIG_FIELDS}


def get_model_config_fields() -> tuple[ModelFieldSpec, ...]:
	"""Return the sampling field specs for any model Configure dialog."""
	return MODEL_CONFIG_FIELDS


class ModelConfigStore:
	"""Persist per-model sampling configuration.

	File: ``%APPDATA%/nvda/AIAssistant/model_configs.json`` with shape
	``{provider_id: {model_id: {field: value}}}``.  Thread-safe.
	"""

	def __init__(self) -> None:
		self._path = _store_path()
		self._lock = threading.RLock()

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def get(self, provider: str, model_id: str) -> dict[str, object]:
		"""Return the pinned sampling values for *model_id* (explicit only)."""
		with self._lock:
			data = self._read()
			return dict(data.get(provider, {}).get(model_id, {}))

	def all(self, provider: str) -> dict[str, dict[str, object]]:
		"""Return every pinned model's sampling values for *provider*.

		Maps ``model_id`` to its explicit pinned values.  Used by the
		LiteRT server config writer so ``config.json`` can carry pins for
		all models, not just the currently active one.
		"""
		with self._lock:
			data = self._read()
			provider_map = data.get(provider, {})
			return {
				model_id: dict(values) for model_id, values in provider_map.items()
			}

	def set(self, provider: str, model_id: str, values: dict[str, object]) -> None:
		"""Persist the pinned sampling values for *model_id*."""
		with self._lock:
			data = self._read()
			data.setdefault(provider, {})[model_id] = dict(values)
			self._write(data)

	def clear(self, provider: str, model_id: str) -> None:
		"""Remove any pinned sampling values for *model_id*."""
		with self._lock:
			data = self._read()
			provider_map = data.get(provider, {})
			if model_id in provider_map:
				del provider_map[model_id]
				self._write(data)

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	def _read(self) -> dict[str, dict[str, dict[str, object]]]:
		try:
			if self._path.exists():
				raw = json.loads(self._path.read_text(encoding="utf-8"))
				if isinstance(raw, dict):
					return raw
		except (json.JSONDecodeError, OSError):
			pass
		return {}

	def _write(self, data: dict[str, dict[str, dict[str, object]]]) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)
		self._path.write_text(
			json.dumps(data, indent=2, sort_keys=True),
			encoding="utf-8",
		)


# ---------------------------------------------------------------------------
# Read / write helpers
# ---------------------------------------------------------------------------


def get_model_thinking(provider_id: str, model_id: str) -> bool:
	"""Return the per-model thinking preference, defaulting to disabled."""
	value = ModelConfigStore().get(provider_id, model_id).get("thinking")
	return value if isinstance(value, bool) else False


def set_model_thinking(provider_id: str, model_id: str, enabled: bool) -> None:
	"""Persist thinking for one model; provider-wide thinking is unsupported."""
	store = ModelConfigStore()
	values = store.get(provider_id, model_id)
	values["thinking"] = bool(enabled)
	store.set(provider_id, model_id, values)


def get_model_sampling(provider_id: str, model_id: str) -> ModelSamplingConfig:
	"""Return the pinned sampling config for *model_id* (explicit values only)."""
	raw = ModelConfigStore().get(provider_id, model_id)
	return ModelSamplingConfig(**{field: raw.get(field) for field in SAMPLING_FIELD_IDS})


def get_all_model_sampling(provider_id: str) -> dict[str, ModelSamplingConfig]:
	"""Return pinned sampling for every model of *provider_id*.

	Explicit values only, keyed by ``model_id``.  The LiteRT server
	config writer uses this to emit ``models.<id>`` entries for all
	pinned models, since litert-lm resolves per-model config at request
	time for whichever model a chat request targets.
	"""
	return {
		model_id: ModelSamplingConfig(
			**{field: raw.get(field) for field in SAMPLING_FIELD_IDS}
		)
		for model_id, raw in ModelConfigStore().all(provider_id).items()
	}


def set_model_sampling(
	provider_id: str,
	model_id: str,
	config: ModelSamplingConfig,
) -> None:
	"""Pin *config* for *model_id*.  ``None`` fields are left unpinned."""
	values = {
		field: value
		for field in SAMPLING_FIELD_IDS
		if (value := getattr(config, field)) is not None
	}
	store = ModelConfigStore()
	# Model-level flags (such as thinking) share this record.  Merge the
	# sampling values so changing sampling does not reset those flags.
	stored = store.get(provider_id, model_id)
	stored.update(values)
	store.set(provider_id, model_id, stored)
	if str(provider_id or "").strip().lower() == "litert-lm":
		# A pinned num_ctx changes the server's per-model max_num_tokens,
		# so the LiteRT server must restart to apply it.
		from .state import _notify_litert_server_config_changed

		_notify_litert_server_config_changed()


def clear_model_sampling(provider_id: str, model_id: str) -> None:
	"""Remove every pinned sampling value for *model_id*."""
	store = ModelConfigStore()
	stored = store.get(provider_id, model_id)
	for field in SAMPLING_FIELD_IDS:
		stored.pop(field, None)
	if stored:
		store.set(provider_id, model_id, stored)
	else:
		store.clear(provider_id, model_id)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_model_sampling(
	provider_id: str,
	model_id: str,
	base: ModelSamplingConfig,
	*,
	local_backend: bool = True,
) -> ModelSamplingConfig:
	"""Merge pinned per-model values over *base*.

	*base* supplies the fallback for wire-fallback fields (temperature,
	top-p, max tokens) — a pinned value wins.  Local-fallback fields
	(``num_ctx``) behave like wire-fallback for *local_backend* but are
	suppressed for cloud providers unless explicitly pinned.  Pinned-only
	fields (top-k, repetition penalty) resolve to ``None`` unless the
	model pins them explicitly, so they are never sent by accident.
	"""
	explicit = get_model_sampling(provider_id, model_id)
	values: dict[str, int | float | None] = {}
	for field in _WIRE_FALLBACK_FIELDS:
		explicit_value = getattr(explicit, field)
		values[field] = (
			explicit_value if explicit_value is not None else getattr(base, field)
		)
	for field in _LOCAL_FALLBACK_FIELDS:
		explicit_value = getattr(explicit, field)
		if local_backend:
			values[field] = (
				explicit_value if explicit_value is not None else getattr(base, field)
			)
		else:
			values[field] = explicit_value if explicit_value is not None else None
	for field in _PINNED_ONLY_FIELDS:
		explicit_value = getattr(explicit, field)
		values[field] = explicit_value if explicit_value is not None else None
	return ModelSamplingConfig(**values)


def effective_field_value(
	provider_id: str,
	model_id: str,
	base: ModelSamplingConfig,
	field_id: str,
) -> int | float:
	"""Return the value a Configure dialog should display for *field_id*.

	Resolution order: pinned model value → provider global setting →
	static default for the field.
	"""
	resolved = resolve_model_sampling(provider_id, model_id, base)
	value = getattr(resolved, field_id)
	if value is not None:
		return value
	return fallback_field_value(base, field_id, MODEL_FIELD_BY_ID.get(field_id))


def fallback_field_value(
	base: ModelSamplingConfig,
	field_id: str,
	spec: ModelFieldSpec | None,
) -> int | float:
	"""Return the value a model uses when *field_id* is left unpinned.

	Resolution order: provider global setting (``base``) → static
	default for the field.  Pinned-only fields (top-k, repetition
	penalty) have no global fallback, so they resolve to their static
	default.  This is what a Configure dialog shows next to a checked
	"Use default" box.
	"""
	value = getattr(base, field_id, None)
	if value is not None:
		return value
	if spec is not None and spec.default is not None:
		return spec.default
	return 0


# ---------------------------------------------------------------------------
# UI title helper (wx-free, testable)
# ---------------------------------------------------------------------------


def model_configure_title(model_name: str) -> str:
	# TRANSLATORS: Title of a model Configure dialog; {name} is the model display name.
	return _("Configure {name}").format(name=model_name)


__all__ = [
	"MODEL_CONFIG_FIELDS",
	"MODEL_FIELD_BY_ID",
	"ModelConfigStore",
	"ModelFieldSpec",
	"ModelSamplingConfig",
	"SAMPLING_FIELD_IDS",
	"clear_model_sampling",
	"effective_field_value",
	"get_model_config_fields",
	"get_model_sampling",
	"model_configure_title",
	"resolve_model_sampling",
	"set_model_sampling",
]
