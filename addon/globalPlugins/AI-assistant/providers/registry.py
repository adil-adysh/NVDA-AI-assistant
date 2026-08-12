# -*- coding: utf-8 -*-
"""Provider metadata and lifecycle registry.

Single source of truth for *which providers exist* and *what state
they are in*.  Defines the provider taxonomy (``ProviderKind``), the
lifecycle state (``ProviderLifecycleState``), and the per-provider
metadata (``ProviderInfo``) that drive the provider-management UI.

The provider-management UI asks this registry:

- What kind of provider are you?  (``ProviderKind``)
- What state are you in?  (``ProviderLifecycleState``)
- What configuration fields do you expose?  (``get_configure_fields``)
- Can you be installed?  (``install_provider`` / ``is_installable``)
- Can you manage models?  (``build_model_manager``)

It must never hardcode provider IDs or branch on provider names itself;
new providers register here instead.

The name ``ProviderLifecycleState`` deliberately avoids colliding with
``config.state.ProviderState``, which is the runtime snapshot of the
*active* provider (provider id + model + backend URL).
"""

from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import cast

from ..config.settings import (
	build_provider_config,
	get_enabled_providers,
	get_provider,
	save,
	set_enabled_providers,
	set_openai_compat_config,
	set_provider,
)
from .adapters.openai_compat import OpenAICompatProvider
from .litert_manager import LiteRTModelManager
from .model_manager import CloudModelManagerAdapter, ModelManagerProvider


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


#: Canonical provider IDs in display/cycle order.
PROVIDER_IDS: tuple[str, ...] = ("ollama", "gemini", "openai", "litert-lm")

#: Human-readable provider names (translate at call time).
_PROVIDER_NAMES: dict[str, str] = {
	"ollama": "Ollama",
	"gemini": "Gemini",
	"openai": "OpenAI",
	"litert-lm": "LiteRT-LM",
}

#: Provider kind per provider ID.
_PROVIDER_KINDS: dict[str, "ProviderKind"] = {
	"ollama": "local",
	"gemini": "cloud",
	"openai": "cloud",
	"litert-lm": "local",
}

#: Providers with an application-managed installation lifecycle.
#: Only these expose an ``Install`` action in the provider UI.
_INSTALLABLE: frozenset[str] = frozenset({"litert-lm"})


class ProviderKind(str, Enum):
	"""Whether a provider is a remote service or a local runtime."""

	CLOUD = "cloud"
	LOCAL = "local"


class ProviderLifecycleState(str, Enum):
	"""Installation/configuration lifecycle state of a provider.

	Valid states depend on provider type:

	- Cloud (and local providers without an install step): ``AVAILABLE``
	  -> ``CONFIGURED``.
	- Local installable providers: ``AVAILABLE`` -> ``NOT_INSTALLED`` ->
	  ``INSTALLED`` -> ``CONFIGURED``.
	"""

	AVAILABLE = "available"
	NOT_INSTALLED = "not_installed"
	INSTALLED = "installed"
	CONFIGURED = "configured"


class ProviderAction(str, Enum):
	"""Operations a provider supports in its current state."""

	INSTALL = "install"
	CONFIGURE = "configure"
	MANAGE_MODELS = "manage_models"


@dataclass(frozen=True)
class ProviderInfo:
	"""Metadata describing a provider to the management UI.

	``state`` is derived from the actual persisted configuration and
	runtime installation state — never from the active model.
	"""

	id: str
	name: str
	kind: ProviderKind
	state: ProviderLifecycleState
	installable: bool = False
	#: Whether the provider is in the persisted enabled set.
	enabled: bool = True
	#: Whether the provider is currently the active AI provider.
	active: bool = False

	@property
	def actions(self) -> tuple[ProviderAction, ...]:
		"""Actions valid for this provider in its current state."""
		if self.kind is ProviderKind.CLOUD or not self.installable:
			# Cloud / non-installable local providers: no install step.
			if self.state is ProviderLifecycleState.CONFIGURED:
				return (ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS)
			return (ProviderAction.CONFIGURE,)
		if self.state in (
			ProviderLifecycleState.AVAILABLE,
			ProviderLifecycleState.NOT_INSTALLED,
		):
			return (ProviderAction.INSTALL,)
		# INSTALLED or CONFIGURED.
		return (ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS)


@dataclass(frozen=True)
class ConfigureFieldSpec:
	"""A single configuration field exposed by a provider's Configure dialog.

	``id`` maps directly onto an ``OpenAICompatConfig`` attribute:
	``api_key``, ``base_url``, ``chat_path``.  ``server_url`` maps onto
	``base_url`` and is used for local runtimes where the URL is the
	connection point.  There are deliberately **no model fields** here —
	model selection belongs to the model manager, never to Configure.

	``kind`` selects the widget rendered by the dialog: ``text``
	(default), ``choice`` (a combo box restricted to ``choices``), or
	``int`` (a numeric spin control).
	"""

	id: str
	# TRANSLATORS: Field label in a provider Configure dialog (subclassed per provider).
	label: str
	secret: bool = False
	required: bool = True
	#: Widget kind: ``"text"``, ``"choice"`` or ``"int"``.
	kind: str = "text"
	#: Allowed values when ``kind == "choice"``.
	choices: tuple[str, ...] = ()
	#: For ``kind == "choice"``, a leading "use engine default" item.  When
	#: selected, the persisted value is ``""`` so the key is omitted from the
	#: server config and litert-lm falls back to its own default.
	default_choice: str = ""


#: Configuration fields exposed by each provider's Configure dialog.
_CONFIGURE_FIELDS: dict[str, tuple[ConfigureFieldSpec, ...]] = {
	"openai": (
		ConfigureFieldSpec("api_key", _("API key:"), secret=True),
		ConfigureFieldSpec("base_url", _("API endpoint:")),
		ConfigureFieldSpec("chat_path", _("Chat path:"), required=False),
	),
	"gemini": (
		ConfigureFieldSpec("api_key", _("API key:"), secret=True),
		ConfigureFieldSpec("base_url", _("API endpoint:")),
	),
	"ollama": (
		ConfigureFieldSpec("server_url", _("Server URL:")),
	),
	"litert-lm": (
		ConfigureFieldSpec("server_url", _("Server URL:")),
		# TRANSLATORS: LiteRT-LM compute backend selection in the Configure dialog; "default" leaves the engine default.
		ConfigureFieldSpec(
			"backend",
			_("Compute backend:"),
			kind="choice",
			choices=("cpu", "gpu", "npu"),
			default_choice="default",
			required=False,
		),
		# TRANSLATORS: LiteRT-LM cache policy selection in the Configure dialog; "default" leaves the engine default.
		ConfigureFieldSpec(
			"cache",
			_("Inference cache:"),
			kind="choice",
			choices=("disk", "memory", "no"),
			default_choice="default",
			required=False,
		),
		# TRANSLATORS: LiteRT-LM CPU thread count in the Configure dialog; 0 means automatic.
		ConfigureFieldSpec(
			"cpu_thread_count",
			_("CPU threads (0 = auto):"),
			kind="int",
			required=False,
		),
	),
}

#: Install hooks keyed by provider ID (only installable providers).


def _install_litert(
	on_progress: Callable[[str], None],
	on_bytes_progress: Callable[[int, int], None],
	cancel_event: threading.Event | None = None,
) -> None:
	from .runtime.server import get_litert_supervisor

	get_litert_supervisor().install(
		on_progress=on_progress,
		on_bytes_progress=on_bytes_progress,
		cancel_event=cancel_event,
	)


_INSTALLERS: dict[str, Callable[..., None]] = {
	"litert-lm": _install_litert,
}


# ---------------------------------------------------------------------------
# Provider capabilities — data-driven replacement for if/elif chains
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderCapabilities:
	"""Data-driven provider differences — replaces scattered if/elif chains.

	Each field answers one question that was previously answered by
	branching on provider ID.  New providers add a row here instead of
	touching ``_has_provider_config``, ``derive_provider_state``,
	``set_think_mode``, or ``_resolve_think_enabled``.
	"""

	#: Credential field groups that must be present for CONFIGURED
	#: state.  Each inner tuple is an "any of" group — at least one
	#: field in the group must have a non-empty value.  Empty tuple
	#: means no credentials are required.
	credential_groups: tuple[tuple[str, ...], ...] = ()

	#: Settings key for the think-mode toggle.  Empty string when the
	#: provider does not support think mode.
	think_config_key: str = ""

	#: Whether this provider has an application-managed install step.
	has_install_step: bool = False


def _litert_install_check() -> bool:
	"""Return ``True`` when the LiteRT-LM runtime is installed on disk."""
	from .runtime.server import get_litert_supervisor

	return get_litert_supervisor().is_installed


#: Provider capabilities keyed by canonical provider ID.
_PROVIDER_CAPABILITIES: dict[str, ProviderCapabilities] = {
	"ollama": ProviderCapabilities(
		think_config_key="ollamaThink",
	),
	"gemini": ProviderCapabilities(
		credential_groups=(("api_key", "api_token"),),
	),
	"openai": ProviderCapabilities(
		credential_groups=(("api_key",),),
	),
	"litert-lm": ProviderCapabilities(
		think_config_key="litertThink",
		has_install_step=True,
	),
}


def get_provider_capabilities(provider_id: str) -> ProviderCapabilities:
	"""Return the :class:`ProviderCapabilities` for *provider_id*.

	Unknown providers return a default (empty) capabilities instance.
	"""
	normalized = str(provider_id or "").strip().lower()
	return _PROVIDER_CAPABILITIES.get(normalized, ProviderCapabilities())


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def provider_display_name(provider_id: str) -> str:
	"""Return the human-readable name for *provider_id*."""
	normalized = str(provider_id or "").strip().lower()
	return _(_PROVIDER_NAMES.get(normalized, normalized))


def provider_kind(provider_id: str) -> ProviderKind:
	"""Return the kind (cloud/local) for *provider_id*."""
	normalized = str(provider_id or "").strip().lower()
	return ProviderKind(_PROVIDER_KINDS.get(normalized, "cloud"))


def is_installable(provider_id: str) -> bool:
	"""Whether *provider_id* has an application-managed install step."""
	return str(provider_id or "").strip().lower() in _INSTALLABLE


def is_runtime_installed(provider_id: str) -> bool:
	"""Whether an installable provider's runtime is installed on disk."""
	normalized = str(provider_id or "").strip().lower()
	if normalized not in _INSTALLABLE:
		return False
	from .runtime.server import get_litert_supervisor

	return get_litert_supervisor().is_installed


def get_configure_fields(provider_id: str) -> tuple[ConfigureFieldSpec, ...]:
	"""Return the configuration field specs for *provider_id*'s Configure dialog."""
	normalized = str(provider_id or "").strip().lower()
	return _CONFIGURE_FIELDS.get(normalized, ())


# ---------------------------------------------------------------------------
# State derivation
# ---------------------------------------------------------------------------


def _has_provider_config(provider_id: str) -> bool:
	"""Whether the provider has a complete persisted configuration.

	``CONFIGURED`` requires the same fields the provider needs to
	operate (model name + connection endpoint, plus credentials for
	cloud providers).  This is deliberately independent from runtime
	health: a LiteRT-LM runtime can be installed and configured while
	its server is not currently running.
	"""
	config = build_provider_config(provider_id)
	model_name = str(config.model_name or "").strip()
	base_url = str(getattr(config, "base_url", "") or "").strip()
	if not model_name:
		return False
	caps = get_provider_capabilities(provider_id)
	for group in caps.credential_groups:
		if not any(
			str(getattr(config, field, "") or "").strip()
			for field in group
		):
			return False
	return bool(base_url)


def derive_provider_state(provider_id: str) -> ProviderLifecycleState:
	"""Derive the lifecycle state for *provider_id* from actual state."""
	normalized = str(provider_id or "").strip().lower()
	caps = get_provider_capabilities(normalized)

	if caps.has_install_step and not _litert_install_check():
		return ProviderLifecycleState.NOT_INSTALLED
	if _has_provider_config(normalized):
		return ProviderLifecycleState.CONFIGURED
	if caps.has_install_step:
		return ProviderLifecycleState.INSTALLED
	return ProviderLifecycleState.AVAILABLE


def get_provider_info(provider_id: str) -> ProviderInfo:
	"""Return the ``ProviderInfo`` for a single provider ID."""
	normalized = str(provider_id or "").strip().lower()
	return ProviderInfo(
		id=normalized,
		name=provider_display_name(normalized),
		kind=provider_kind(normalized),
		state=derive_provider_state(normalized),
		installable=is_installable(normalized),
		enabled=normalized in get_enabled_providers(),
		active=normalized == get_provider(),
	)


def get_provider_infos() -> tuple[ProviderInfo, ...]:
	"""Return metadata for every registered provider, in canonical order."""
	return tuple(get_provider_info(pid) for pid in PROVIDER_IDS)


# ---------------------------------------------------------------------------
# Enable / disable and active-provider switching
# ---------------------------------------------------------------------------


def set_provider_enabled(provider_id: str, enabled: bool) -> None:
	"""Enable or disable *provider_id* in the persisted enabled set.

	Refuses (``ValueError``) to disable the last enabled provider so the
	assistant always keeps at least one usable provider.  The UI layer is
	responsible for active-provider handling (warn + switch) *before*
	calling this.
	"""
	normalized = str(provider_id or "").strip().lower()
	current = get_enabled_providers()
	if enabled:
		if normalized not in current:
			set_enabled_providers([*current, normalized])
		return
	if normalized not in current:
		return
	if len(current) <= 1:
		# TRANSLATORS: Error when the user tries to disable the last enabled provider.
		raise ValueError(_("At least one provider must remain enabled."))
	set_enabled_providers([p for p in current if p != normalized])


def set_active_provider(provider_id: str) -> None:
	"""Make *provider_id* the active AI provider (persisted).

	Only enabled providers can become active; disabled providers raise
	``ValueError``.
	"""
	normalized = str(provider_id or "").strip().lower()
	if normalized not in get_enabled_providers():
		# TRANSLATORS: Error when trying to activate a disabled provider; {name} is the provider name.
		raise ValueError(
			_("{name} is not enabled.").format(name=provider_display_name(normalized))
		)
	set_provider(normalized)
	save()


# ---------------------------------------------------------------------------
# Model manager construction
# ---------------------------------------------------------------------------


def _make_set_model(provider_id: str) -> Callable[[str], None]:
	"""Return a ``set_model_fn`` persisting the active model for *provider_id*.

	The config is rebuilt from the *provider's own* YAML keys so that
	switching the active model never clobbers the target provider's
	other settings (base URL, API key, etc.) with the active provider's
	values.  Selecting an active model also activates its provider —
	this matches the historical model-manager behavior.
	"""

	def _set(model_id: str) -> None:
		cfg = build_provider_config(provider_id)
		set_openai_compat_config(
			type(cfg)(
				**{**vars(cfg), "provider": provider_id, "model_name": model_id},
			)
		)

	return _set


def build_model_manager(provider_id: str) -> ModelManagerProvider:
	"""Construct the model manager for *provider_id*.

	The returned object is bound to that provider — the model manager
	dialog opened from a provider must never re-ask which provider to
	manage.  A ``ModelCatalogCache`` reference is injected so that the
	initial dialog load can be served from the startup cache without
	a network round-trip.
	"""
	normalized = str(provider_id or "").strip().lower()
	config = build_provider_config(normalized)
	if normalized == "litert-lm":
		return LiteRTModelManager(config=config)
	# Lazy-import the cache to avoid circular deps at module level.
	from ..service.model_cache import model_catalog_cache
	return CloudModelManagerAdapter(
		provider_id=normalized,
		config=config,
		provider_class=OpenAICompatProvider,
		set_model_fn=_make_set_model(normalized),
		get_config_fn=lambda: build_provider_config(normalized),
		model_cache=model_catalog_cache,
	)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install_provider(
	provider_id: str,
	on_progress: Callable[[str], None],
	on_bytes_progress: Callable[[int, int], None],
	cancel_event: threading.Event | None = None,
) -> None:
	"""Run the installation routine for *provider_id* (blocking).

	Runs in a background thread — callers must dispatch UI updates via
	``wx.CallAfter`` or equivalent.  Raises if the provider has no
	install hook.

	*cancel_event* (optional) allows the caller to request cancellation;
	partial downloads are preserved for future resume.
	"""
	normalized = str(provider_id or "").strip().lower()
	installer = _INSTALLERS.get(normalized)
	if installer is None:
		raise ValueError(f"Provider '{normalized}' is not installable")
	installer(on_progress, on_bytes_progress, cancel_event=cancel_event)


# ---------------------------------------------------------------------------
# UI title helpers (wx-free, testable)
# ---------------------------------------------------------------------------


def configure_dialog_title(provider_name: str) -> str:
	# TRANSLATORS: Title of a provider Configure dialog; {name} is the provider name.
	return _("Configure {name}").format(name=provider_name)


def model_manager_title(provider_name: str) -> str:
	# TRANSLATORS: Title of a provider-specific model manager dialog; {name} is the provider name.
	return _("{name} — Manage Models").format(name=provider_name)


def provider_state_label(state: ProviderLifecycleState) -> str:
	"""User-facing label for a lifecycle state (accessible text, not icons)."""
	if state is ProviderLifecycleState.AVAILABLE:
		# TRANSLATORS: Provider lifecycle status shown in the provider list.
		return _("Available")
	if state is ProviderLifecycleState.NOT_INSTALLED:
		# TRANSLATORS: Provider lifecycle status shown in the provider list.
		return _("Not Installed")
	if state is ProviderLifecycleState.INSTALLED:
		# TRANSLATORS: Provider lifecycle status shown in the provider list.
		return _("Installed")
	# TRANSLATORS: Provider lifecycle status shown in the provider list.
	return _("Configured")


def provider_kind_label(kind: ProviderKind) -> str:
	"""User-facing label for a provider kind."""
	if kind is ProviderKind.CLOUD:
		# TRANSLATORS: Provider type shown in the provider list.
		return _("Cloud")
	# TRANSLATORS: Provider type shown in the provider list.
	return _("Local")


__all__ = [
	"ConfigureFieldSpec",
	"PROVIDER_IDS",
	"ProviderAction",
	"ProviderInfo",
	"ProviderKind",
	"ProviderLifecycleState",
	"build_model_manager",
	"configure_dialog_title",
	"derive_provider_state",
	"get_configure_fields",
	"get_provider_info",
	"get_provider_infos",
	"install_provider",
	"is_installable",
	"is_runtime_installed",
	"model_manager_title",
	"provider_display_name",
	"provider_kind",
	"provider_kind_label",
	"provider_state_label",
	"set_active_provider",
	"set_provider_enabled",
]
