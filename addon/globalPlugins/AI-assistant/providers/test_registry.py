# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "provider_registry_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.providers.adapters", [])
_register_package(f"{PACKAGE_NAME}.providers.runtime", [])

log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(
	debug=lambda *args, **kwargs: None,
	warning=lambda *args, **kwargs: None,
	exception=lambda *args, **kwargs: None,
)
sys.modules["logHandler"] = log_handler_module

config_module = _load_module(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)

# ---------------------------------------------------------------------------
# Stubs for the registry's imports
# ---------------------------------------------------------------------------

_configs: dict[str, object] = {}


def _make_config(
	provider: str,
	model_name: str = "",
	base_url: str = "",
	api_key: str = "",
	api_token: str | None = None,
	chat_path: str = "/v1/chat/completions",
):
	return config_module.OpenAICompatConfig(
		provider=provider,
		model_name=model_name,
		base_url=base_url,
		api_key=api_key,
		api_token=api_token,
		chat_path=chat_path,
		timeout_seconds=30.0,
		enable_progress=False,
		num_ctx=0,
		max_retries=1,
		retry_backoff_seconds=0.1,
		generate_temperature=0.2,
		generate_top_k=0,
		generate_top_p=0.9,
		generate_max_tokens=512,
		think=False,
	)


def _set_config(provider: str, config: object) -> None:
	_configs[provider] = config


def _reset_configs() -> None:
	_configs.clear()


def _build_provider_config(provider: str) -> object:
	if provider in _configs:
		return _configs[provider]
	return _make_config(provider)


saved_calls: list[tuple[object, bool]] = []


def _set_openai_compat_config(config: object, activate: bool = True) -> None:
	saved_calls.append((config, activate))


_enabled_providers: list[str] = ["ollama", "gemini", "openai", "litert-lm"]
_active_provider: str = "ollama"
save_calls: list[bool] = []


def _get_enabled_providers() -> list[str]:
	return list(_enabled_providers)


def _set_enabled_providers(providers: list[str]) -> None:
	global _enabled_providers  # pylint: disable=global-statement
	_enabled_providers = list(providers)


def _get_provider() -> str:
	return _active_provider


def _set_provider(provider: str) -> None:
	global _active_provider  # pylint: disable=global-statement
	_active_provider = provider


def _save() -> None:
	save_calls.append(True)


settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
settings_module.build_provider_config = _build_provider_config
settings_module.set_openai_compat_config = _set_openai_compat_config
settings_module.get_enabled_providers = _get_enabled_providers
settings_module.set_enabled_providers = _set_enabled_providers
settings_module.get_provider = _get_provider
settings_module.set_provider = _set_provider
settings_module.save = _save
sys.modules[settings_module.__name__] = settings_module

# Test-visible aliases for the stubbed settings surface.
get_enabled_providers = _get_enabled_providers
get_provider = _get_provider


class _FakeFeatures:
	def __init__(self, download: bool, delete: bool) -> None:
		self.download = download
		self.delete = delete


class _FakeCloudAdapter:
	# Parameters mirror the real CloudModelManagerAdapter constructor
	# signature (keyword-called by the registry), so unused ones stay.
	# pylint: disable=unused-argument

	def __init__(
		self,
		provider_id: str,
		config: object,
		provider_class: object,
		set_model_fn: object,
		get_config_fn: object | None = None,
	) -> None:
		self.provider_id = provider_id
		self.config = config
		self.features = _FakeFeatures(False, False)
		self.set_model_fn = set_model_fn

	def set_active_model(self, model_id: str) -> None:
		self.set_model_fn(model_id)


model_manager_module = types.ModuleType(f"{PACKAGE_NAME}.providers.model_manager")
model_manager_module.ModelManagerProvider = type("ModelManagerProvider", (), {})
model_manager_module.CloudModelManagerAdapter = _FakeCloudAdapter
sys.modules[model_manager_module.__name__] = model_manager_module


class _FakeLiteRTManager:
	provider_id = "litert-lm"

	def __init__(self, config: object | None = None) -> None:
		self.config = config
		self.features = _FakeFeatures(True, True)


litert_manager_module = types.ModuleType(f"{PACKAGE_NAME}.providers.litert_manager")
litert_manager_module.LiteRTModelManager = _FakeLiteRTManager
sys.modules[litert_manager_module.__name__] = litert_manager_module

openai_compat_module = types.ModuleType(
	f"{PACKAGE_NAME}.providers.adapters.openai_compat",
)
openai_compat_module.OpenAICompatProvider = type("OpenAICompatProvider", (), {})
sys.modules[openai_compat_module.__name__] = openai_compat_module

# Fake LiteRT supervisor: is_installed + install() recording.
_installed = False
_install_calls = []


class _FakeSupervisor:
	@property
	def is_installed(self) -> bool:
		return _installed

	def install(self, on_progress=None, on_bytes_progress=None) -> None:
		_install_calls.append((on_progress, on_bytes_progress))


def _set_installed(value: bool) -> None:
	global _installed  # pylint: disable=global-statement
	_installed = value


runtime_server_module = types.ModuleType(f"{PACKAGE_NAME}.providers.runtime.server")
runtime_server_module.get_litert_supervisor = _FakeSupervisor
sys.modules[runtime_server_module.__name__] = runtime_server_module

registry_module = _load_module(
	f"{PACKAGE_NAME}.providers.registry",
	ROOT_DIR / "providers" / "registry.py",
)

ProviderAction = registry_module.ProviderAction
ProviderInfo = registry_module.ProviderInfo
ProviderKind = registry_module.ProviderKind
ProviderLifecycleState = registry_module.ProviderLifecycleState
build_model_manager = registry_module.build_model_manager
configure_dialog_title = registry_module.configure_dialog_title
derive_provider_state = registry_module.derive_provider_state
get_configure_fields = registry_module.get_configure_fields
get_provider_info = registry_module.get_provider_info
get_provider_infos = registry_module.get_provider_infos
install_provider = registry_module.install_provider
is_installable = registry_module.is_installable
model_manager_title = registry_module.model_manager_title
provider_display_name = registry_module.provider_display_name
provider_kind = registry_module.provider_kind
provider_kind_label = registry_module.provider_kind_label
provider_state_label = registry_module.provider_state_label
set_active_provider = registry_module.set_active_provider
set_provider_enabled = registry_module.set_provider_enabled


class ProviderInfoActionMatrixTests(unittest.TestCase):
	"""Provider type/state → available actions matrix (spec sections 6-8, 40)."""

	def test_cloud_available_configure_only(self) -> None:
		for provider in ("openai", "gemini"):
			info = ProviderInfo(
				id=provider,
				name=provider,
				kind=ProviderKind.CLOUD,
				state=ProviderLifecycleState.AVAILABLE,
			)
			self.assertEqual(info.actions, (ProviderAction.CONFIGURE,))

	def test_cloud_configured_configure_and_models(self) -> None:
		for provider in ("openai", "gemini"):
			info = ProviderInfo(
				id=provider,
				name=provider,
				kind=ProviderKind.CLOUD,
				state=ProviderLifecycleState.CONFIGURED,
			)
			self.assertEqual(
				info.actions,
				(ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS),
			)

	def test_local_not_installed_install_only(self) -> None:
		info = ProviderInfo(
			id="litert-lm",
			name="LiteRT-LM",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.NOT_INSTALLED,
			installable=True,
		)
		self.assertEqual(info.actions, (ProviderAction.INSTALL,))

	def test_local_available_install_only(self) -> None:
		info = ProviderInfo(
			id="litert-lm",
			name="LiteRT-LM",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.AVAILABLE,
			installable=True,
		)
		self.assertEqual(info.actions, (ProviderAction.INSTALL,))

	def test_local_installed_configure_and_models(self) -> None:
		info = ProviderInfo(
			id="litert-lm",
			name="LiteRT-LM",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.INSTALLED,
			installable=True,
		)
		self.assertEqual(
			info.actions,
			(ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS),
		)

	def test_local_configured_configure_and_models(self) -> None:
		info = ProviderInfo(
			id="litert-lm",
			name="LiteRT-LM",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.CONFIGURED,
			installable=True,
		)
		self.assertEqual(
			info.actions,
			(ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS),
		)

	def test_ollama_local_non_installable_never_installs(self) -> None:
		# Ollama is local but has no app-managed install step: its lifecycle
		# collapses to the cloud-style Available/Configured pair.
		available = ProviderInfo(
			id="ollama",
			name="Ollama",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.AVAILABLE,
		)
		self.assertEqual(available.actions, (ProviderAction.CONFIGURE,))
		configured = ProviderInfo(
			id="ollama",
			name="Ollama",
			kind=ProviderKind.LOCAL,
			state=ProviderLifecycleState.CONFIGURED,
		)
		self.assertEqual(
			configured.actions,
			(ProviderAction.CONFIGURE, ProviderAction.MANAGE_MODELS),
		)


class ProviderKindTests(unittest.TestCase):
	def test_kind_mapping(self) -> None:
		self.assertIs(provider_kind("openai"), ProviderKind.CLOUD)
		self.assertIs(provider_kind("gemini"), ProviderKind.CLOUD)
		self.assertIs(provider_kind("ollama"), ProviderKind.LOCAL)
		self.assertIs(provider_kind("litert-lm"), ProviderKind.LOCAL)

	def test_installable_only_litert(self) -> None:
		self.assertTrue(is_installable("litert-lm"))
		self.assertFalse(is_installable("ollama"))
		self.assertFalse(is_installable("openai"))
		self.assertFalse(is_installable("gemini"))

	def test_all_providers_registered_in_order(self) -> None:
		infos = get_provider_infos()
		self.assertEqual(
			[info.id for info in infos],
			["ollama", "gemini", "openai", "litert-lm"],
		)

	def test_display_name(self) -> None:
		self.assertEqual(provider_display_name("litert-lm"), "LiteRT-LM")
		self.assertEqual(provider_display_name("openai"), "OpenAI")


class ProviderStateDerivationTests(unittest.TestCase):
	def setUp(self) -> None:
		_reset_configs()
		_set_installed(False)

	def test_cloud_unconfigured_is_available(self) -> None:
		_set_config(
			"openai",
			_make_config("openai", model_name="", base_url=""),
		)
		self.assertEqual(
			derive_provider_state("openai"),
			ProviderLifecycleState.AVAILABLE,
		)

	def test_cloud_missing_credentials_is_available(self) -> None:
		# Base URL + model but no API key -> not configured.
		_set_config(
			"openai",
			_make_config("openai", model_name="gpt-4o", base_url="https://api.openai.com"),
		)
		self.assertEqual(
			derive_provider_state("openai"),
			ProviderLifecycleState.AVAILABLE,
		)

	def test_cloud_configured(self) -> None:
		_set_config(
			"openai",
			_make_config(
				"openai",
				model_name="gpt-4o",
				base_url="https://api.openai.com",
				api_key="sk-test",
			),
		)
		self.assertEqual(
			derive_provider_state("openai"),
			ProviderLifecycleState.CONFIGURED,
		)

	def test_gemini_token_counts_as_credentials(self) -> None:
		_set_config(
			"gemini",
			_make_config(
				"gemini",
				model_name="gemini-flash",
				base_url="https://generativelanguage.googleapis.com",
				api_token="bearer-token",
			),
		)
		self.assertEqual(
			derive_provider_state("gemini"),
			ProviderLifecycleState.CONFIGURED,
		)

	def test_litert_not_installed(self) -> None:
		_set_installed(False)
		self.assertEqual(
			derive_provider_state("litert-lm"),
			ProviderLifecycleState.NOT_INSTALLED,
		)

	def test_litert_installed_unconfigured(self) -> None:
		_set_installed(True)
		_set_config("litert-lm", _make_config("litert-lm"))
		self.assertEqual(
			derive_provider_state("litert-lm"),
			ProviderLifecycleState.INSTALLED,
		)

	def test_litert_installed_configured(self) -> None:
		_set_installed(True)
		_set_config(
			"litert-lm",
			_make_config(
				"litert-lm",
				model_name="litert-community/gemma-4-E2B-it-litert-lm",
				base_url="http://127.0.0.1:9379",
			),
		)
		self.assertEqual(
			derive_provider_state("litert-lm"),
			ProviderLifecycleState.CONFIGURED,
		)

	def test_litert_not_installed_ignores_config(self) -> None:
		# Provider state is independent of the active model: even with a
		# full config, an uninstalled runtime stays NOT_INSTALLED.
		_set_installed(False)
		_set_config(
			"litert-lm",
			_make_config(
				"litert-lm",
				model_name="gemma",
				base_url="http://127.0.0.1:9379",
			),
		)
		self.assertEqual(
			derive_provider_state("litert-lm"),
			ProviderLifecycleState.NOT_INSTALLED,
		)

	def test_ollama_unconfigured_is_available(self) -> None:
		_set_config("ollama", _make_config("ollama"))
		self.assertEqual(
			derive_provider_state("ollama"),
			ProviderLifecycleState.AVAILABLE,
		)

	def test_ollama_configured(self) -> None:
		_set_config(
			"ollama",
			_make_config(
				"ollama",
				model_name="ministral-3:3b",
				base_url="http://127.0.0.1:11434",
			),
		)
		self.assertEqual(
			derive_provider_state("ollama"),
			ProviderLifecycleState.CONFIGURED,
		)

	def test_get_provider_info_includes_kind_and_state(self) -> None:
		_set_installed(False)
		info = get_provider_info("litert-lm")
		self.assertEqual(info.id, "litert-lm")
		self.assertIs(info.kind, ProviderKind.LOCAL)
		self.assertEqual(info.state, ProviderLifecycleState.NOT_INSTALLED)
		self.assertTrue(info.installable)


class ModelManagerConstructionTests(unittest.TestCase):
	"""Manage Models receives the selected provider (spec sections 18, 39, 42)."""

	def setUp(self) -> None:
		_reset_configs()
		saved_calls.clear()

	def test_litert_builds_local_manager_with_download(self) -> None:
		manager = build_model_manager("litert-lm")
		self.assertEqual(manager.provider_id, "litert-lm")
		self.assertTrue(manager.features.download)
		self.assertTrue(manager.features.delete)

	def test_openai_builds_cloud_adapter_for_openai(self) -> None:
		# OpenAI -> Manage Models must manage OpenAI models, never Gemini's.
		manager = build_model_manager("openai")
		self.assertEqual(manager.provider_id, "openai")
		self.assertFalse(manager.features.download)

	def test_gemini_builds_cloud_adapter_for_gemini(self) -> None:
		manager = build_model_manager("gemini")
		self.assertEqual(manager.provider_id, "gemini")

	def test_set_active_model_persists_for_provider(self) -> None:
		_set_config(
			"openai",
			_make_config(
				"openai",
				model_name="gpt-4o",
				base_url="https://api.openai.com",
				api_key="sk-test",
			),
		)
		manager = build_model_manager("openai")
		manager.set_active_model("gpt-4o-mini")
		self.assertEqual(len(saved_calls), 1)
		config, activate = saved_calls[0]
		self.assertEqual(config.provider, "openai")
		self.assertEqual(config.model_name, "gpt-4o-mini")
		self.assertEqual(config.base_url, "https://api.openai.com")
		self.assertTrue(activate)


class ConfigureFieldSpecTests(unittest.TestCase):
	"""Configure dialogs must never contain model fields (spec sections 12-16, 38, 41)."""

	def test_no_model_fields_for_any_provider(self) -> None:
		for provider in ("openai", "gemini", "ollama", "litert-lm"):
			for spec in get_configure_fields(provider):
				self.assertNotIn("model", spec.id)
				self.assertNotIn("model", spec.label.lower())

	def test_openai_fields(self) -> None:
		fields = {spec.id: spec for spec in get_configure_fields("openai")}
		self.assertIn("api_key", fields)
		self.assertIn("base_url", fields)
		self.assertIn("chat_path", fields)
		self.assertTrue(fields["api_key"].secret)

	def test_gemini_fields(self) -> None:
		fields = {spec.id: spec for spec in get_configure_fields("gemini")}
		self.assertIn("api_key", fields)
		self.assertIn("base_url", fields)
		self.assertNotIn("chat_path", fields)

	def test_ollama_fields(self) -> None:
		fields = {spec.id: spec for spec in get_configure_fields("ollama")}
		self.assertEqual(fields, {"server_url": fields["server_url"]})

	def test_litert_fields_no_model_selection(self) -> None:
		fields = {spec.id: spec for spec in get_configure_fields("litert-lm")}
		self.assertEqual(
			set(fields),
			{"server_url", "backend", "cache", "cpu_thread_count"},
		)
		self.assertEqual(fields["backend"].kind, "choice")
		self.assertEqual(fields["backend"].choices, ("cpu", "gpu", "npu"))
		self.assertEqual(fields["backend"].default_choice, "default")
		self.assertEqual(fields["cache"].kind, "choice")
		self.assertEqual(fields["cache"].choices, ("disk", "memory", "no"))
		self.assertEqual(fields["cache"].default_choice, "default")
		self.assertEqual(fields["cpu_thread_count"].kind, "int")
		self.assertFalse(fields["backend"].required)
		self.assertFalse(fields["cache"].required)
		self.assertFalse(fields["cpu_thread_count"].required)


class DialogTitleTests(unittest.TestCase):
	"""Dialog titles identify the provider (spec sections 45, 54)."""

	def test_configure_title_identifies_provider(self) -> None:
		self.assertEqual(configure_dialog_title("OpenAI"), "Configure OpenAI")
		self.assertIn("LiteRT-LM", configure_dialog_title("LiteRT-LM"))

	def test_model_manager_title_identifies_provider(self) -> None:
		title = model_manager_title("LiteRT-LM")
		self.assertIn("LiteRT-LM", title)
		self.assertIn("Manage Models", title)


class StateLabelTests(unittest.TestCase):
	"""Accessible state text, exact terminology (spec sections 46-47)."""

	def test_state_labels(self) -> None:
		self.assertEqual(provider_state_label(ProviderLifecycleState.AVAILABLE), "Available")
		self.assertEqual(provider_state_label(ProviderLifecycleState.NOT_INSTALLED), "Not Installed")
		self.assertEqual(provider_state_label(ProviderLifecycleState.INSTALLED), "Installed")
		self.assertEqual(provider_state_label(ProviderLifecycleState.CONFIGURED), "Configured")

	def test_kind_labels(self) -> None:
		self.assertEqual(provider_kind_label(ProviderKind.CLOUD), "Cloud")
		self.assertEqual(provider_kind_label(ProviderKind.LOCAL), "Local")


class InstallationTests(unittest.TestCase):
	def setUp(self) -> None:
		_install_calls.clear()

	def test_install_dispatches_to_runtime(self) -> None:
		install_provider("litert-lm", on_progress=lambda _m: None, on_bytes_progress=lambda _d, _t: None)
		self.assertEqual(len(_install_calls), 1)

	def test_install_unknown_provider_raises(self) -> None:
		with self.assertRaises(ValueError):
			install_provider("openai", on_progress=lambda _m: None, on_bytes_progress=lambda _d, _t: None)


class ProviderEnableDisableTests(unittest.TestCase):
	"""Enable/disable and active-provider switching (P0/P2)."""

	def setUp(self) -> None:
		_reset_configs()
		_set_installed(False)
		global _enabled_providers, _active_provider  # pylint: disable=global-statement
		_enabled_providers = ["ollama", "gemini", "openai", "litert-lm"]
		_active_provider = "ollama"
		saved_calls.clear()
		save_calls.clear()

	def test_provider_info_derives_enabled_and_active(self) -> None:
		info = get_provider_info("ollama")
		self.assertTrue(info.enabled)
		self.assertTrue(info.active)
		disabled = get_provider_info("gemini")
		self.assertTrue(disabled.enabled)
		self.assertFalse(disabled.active)

	def test_provider_info_marks_disabled(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama"]
		info = get_provider_info("gemini")
		self.assertFalse(info.enabled)
		self.assertFalse(info.active)

	def test_get_provider_infos_carries_enabled_state(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama", "openai"]
		by_id = {info.id: info for info in get_provider_infos()}
		self.assertTrue(by_id["ollama"].enabled)
		self.assertFalse(by_id["gemini"].enabled)
		self.assertTrue(by_id["openai"].enabled)
		self.assertFalse(by_id["litert-lm"].enabled)

	def test_enable_adds_to_persisted_set(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama"]
		set_provider_enabled("gemini", True)
		self.assertIn("gemini", get_enabled_providers())

	def test_enable_already_enabled_is_noop(self) -> None:
		set_provider_enabled("gemini", True)
		self.assertEqual(
			get_enabled_providers(),
			["ollama", "gemini", "openai", "litert-lm"],
		)

	def test_disable_removes_from_persisted_set(self) -> None:
		set_provider_enabled("openai", False)
		self.assertNotIn("openai", get_enabled_providers())
		self.assertEqual(get_enabled_providers(), ["ollama", "gemini", "litert-lm"])

	def test_disable_last_enabled_provider_raises(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama"]
		with self.assertRaises(ValueError):
			set_provider_enabled("ollama", False)
		# The disabled provider must remain enabled.
		self.assertEqual(get_enabled_providers(), ["ollama"])

	def test_disable_already_disabled_is_noop(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama"]
		set_provider_enabled("gemini", False)
		self.assertEqual(get_enabled_providers(), ["ollama"])


class SetActiveProviderTests(unittest.TestCase):
	"""set_active_provider guards and persistence."""

	def setUp(self) -> None:
		global _active_provider, _enabled_providers  # pylint: disable=global-statement
		_active_provider = "ollama"
		_enabled_providers = ["ollama", "gemini", "openai", "litert-lm"]
		save_calls.clear()

	def test_activates_enabled_provider_and_saves(self) -> None:
		set_active_provider("gemini")
		self.assertEqual(get_provider(), "gemini")
		self.assertEqual(save_calls, [True])

	def test_activating_already_active_is_idempotent(self) -> None:
		set_active_provider("ollama")
		self.assertEqual(get_provider(), "ollama")
		self.assertEqual(save_calls, [True])

	def test_disabled_provider_cannot_become_active(self) -> None:
		global _enabled_providers  # pylint: disable=global-statement
		_enabled_providers = ["ollama"]
		with self.assertRaises(ValueError):
			set_active_provider("gemini")
		self.assertEqual(get_provider(), "ollama")
		self.assertEqual(save_calls, [])


if __name__ == "__main__":
	unittest.main()
