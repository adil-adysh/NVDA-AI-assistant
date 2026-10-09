# -*- coding: utf-8 -*-
"""Milestone 2 Slice 8 Empirical Concurrency & Thread Elimination Challenge Suite.

Adversarial Tests & Stress Verification:
1. Thread Elimination Invariants:
   - Verify that NO threads named 'litert-restart-on-config-change',
     'llama-shutdown-on-config-change', 'LiteRTServerShutdown', or
     'LlamaServerShutdown' are EVER instantiated or started under any
     conditions (config changes, provider state transitions, server ready
     checks, or application termination).
2. AST & Symbol Purge Verification:
   - Verify that '_ensure_litert_server_ready_locked' does NOT exist anywhere
     in the codebase.
   - Verify that '_on_litert_server_config_changed',
     '_restart_litert_server_worker', and '_on_llama_server_config_changed'
     do NOT exist in 'plugin/background.py'.
   - Verify that production test shims '_TestShimSupervisor' and
     '_LlamaTestShimSupervisor' are completely deleted from 'addon/'.
3. AIAssistantApplication.terminate() Real-Class Stress Testing:
   - Real AIAssistantApplication class loaded and instantiated.
   - High-concurrency shutdown under active, in-flight background worker threads.
   - Concurrent provider state updates and model preloads during terminate().
   - Verification that terminate() does not hang, deadlock, or leak unmanaged threads.
   - Idempotency & multi-threaded termination race stress.
   - Late result delivery suppression verification.
4. Invariant A14 (Zero Silent Fallbacks) Adversarial Challenge:
   - Reject unknown/malformed models without modifying settings or attempting startup.
"""

from __future__ import annotations

import ast
import logging
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.support import ADDON_ROOT, register_package, load_module

CHALLENGE_NAMESPACE = "slice8_challenge_pkg"
register_package(CHALLENGE_NAMESPACE, ADDON_ROOT)
register_package(f"{CHALLENGE_NAMESPACE}.plugin", ADDON_ROOT / "plugin")
for pkg in ("config", "providers", "providers.runtime", "service", "ui", "use_case", "context", "context.extractors", "utils"):
	register_package(f"{CHALLENGE_NAMESPACE}.{pkg}", ADDON_ROOT.joinpath(*pkg.split(".")))


def _stub_module(relative_name: str, **attributes: object) -> types.ModuleType:
	mod_name = f"{CHALLENGE_NAMESPACE}.{relative_name}"
	mod = types.ModuleType(mod_name)
	for k, v in attributes.items():
		setattr(mod, k, v)
	sys.modules[mod_name] = mod
	return mod


class _LLMProviderError(RuntimeError):
	pass


class _ProviderConfigurationError(RuntimeError):
	pass


class _LiteRTServerError(RuntimeError):
	pass


sys.modules["addonHandler"] = types.SimpleNamespace(initTranslation=lambda: None)
sys.modules["logHandler"] = types.SimpleNamespace(log=logging.getLogger("test"))

_stub_module(
	"providers.interfaces",
	LLMProviderError=_LLMProviderError,
	ProviderConfigurationError=_ProviderConfigurationError,
)
_stub_module(
	"providers.runtime.server",
	LiteRTServerError=_LiteRTServerError,
	get_litert_supervisor=lambda: types.SimpleNamespace(
		is_installed=True,
		is_running=False,
		matches_current_configuration=lambda: True,
		start=lambda **kw: None,
		stop=lambda: None,
		wait_until_ready=lambda **kw: True,
		list_server_models=lambda: ["model-1"],
		catalog_model_dir=lambda _m: None,
	),
)
_stub_module("providers.llama_manager", LlamaCppModelManager=MagicMock)
_stub_module(
	"service.error_reporter",
	ErrorContext=lambda **kwargs: kwargs,
	error_reporter=types.SimpleNamespace(report=lambda *_args, **_kwargs: None),
)
_stub_module("service.llm", LLMService=object)
_stub_module(
	"service.model_cache",
	model_catalog_cache=types.SimpleNamespace(
		refresh_async=lambda _p: None,
		preload_all=lambda: None,
	),
)
_stub_module(
	"service.provider_readiness",
	ProviderReadinessService=lambda: types.SimpleNamespace(
		evaluate_active=lambda: types.SimpleNamespace(provider="none", can_infer=False)
	),
	get_provider_display_name=lambda p: str(p),
)
_stub_module(
	"config.settings",
	get_provider=lambda: "litert-lm",
	get_model_name=lambda: "model-1",
	get_active_provider_config=lambda: types.SimpleNamespace(provider="litert-lm", model_name="model-1"),
	set_model_name=lambda _name: None,
	get_enabled_providers=lambda: ["litert-lm"],
	get_llama_start_on_startup=lambda: False,
	get_litert_start_on_startup=lambda: False,
	get_provider_state=lambda: types.SimpleNamespace(provider="litert-lm", model_name="model-1", backend_url=""),
	register_language_resolver=lambda _cb: None,
)
_stub_module(
	"config.state",
	subscribe_provider_state_change=lambda _cb: None,
	unsubscribe_provider_state_change=lambda _cb: None,
	subscribe_litert_server_config_change=lambda _cb: None,
	subscribe_llama_server_config_change=lambda _cb: None,
	unsubscribe_litert_server_config_change=lambda _cb: None,
	unsubscribe_llama_server_config_change=lambda _cb: None,
	ProviderState=types.SimpleNamespace,
)
_stub_module("ui.nvda_ui", queue=lambda *_args: None, message=lambda *_args: None, call=lambda *_args: None)
_stub_module("ui.session_state", build_provider_status_message=lambda *_args: "")
_stub_module("use_case.engine", UseCaseEngine=object)
_stub_module(
	"use_case.types",
	ATTACH_FOCUSED_IMAGE_TO_CHAT="attach-focused",
	DESCRIBE_FOCUSED_IMAGE="describe-focused",
	DESCRIBE_IMAGE="describe-image",
	OPEN_CHAT="open-chat",
	OPEN_CHAT_WITH_PAGE_CONTENT="open-page-chat",
	OPEN_CHAT_WITH_SCREENSHOT="open-screenshot-chat",
	STRUCTURE_SUMMARY="structure-summary",
	SUMMARY="summary",
	PROOFREAD="proofread",
	UseCaseId=str,
)

# Stubs for real application.py loading
_stub_module("context.extractors.selection", safe_extract_selection=lambda: None)
_stub_module("context.graph_store", save_accessibility_graph=lambda *a, **k: Path("test.json"))
_stub_module("service", get_provider_display_name=str, provider_control_service=types.SimpleNamespace())
_stub_module("ui.host_process", stop_host=lambda: None)
_stub_module("ui.adapter", ui_adapter=types.SimpleNamespace(register_provider_ready_handler=lambda h: None))
_stub_module("utils.clipboard", safe_read_clipboard=lambda: None)
_stub_module("plugin.factory", build_plugin_services=lambda: types.SimpleNamespace(
	chat_coordinator=None, conversation_service=None, tool_registry=None,
	llm_service=types.SimpleNamespace(ensure_model_available=lambda on_progress=None: "model-1"),
	use_case_engine=types.SimpleNamespace(execute=lambda u, progress=None: types.SimpleNamespace(message="ok")),
	provider=types.SimpleNamespace(close=MagicMock()),
))
_stub_module("plugin.layer_mode", AssistantLayerController=lambda **k: types.SimpleNamespace(activate=lambda: None))
_stub_module("plugin.local_provider_startup", schedule_active_local_provider_start=lambda **k: None)
_stub_module("plugin.presenter", UseCasePresenter=lambda **k: types.SimpleNamespace(
	progress_handler=lambda p: None, present_use_case_error=lambda t, m: None,
	update_provider_state=lambda s: None, close=MagicMock(),
	present_use_case_result=MagicMock(), open_chat_window=MagicMock(),
))
_stub_module("plugin.types", PluginServices=object)

bg_mod = load_module(
	f"{CHALLENGE_NAMESPACE}.plugin.background",
	ADDON_ROOT / "plugin" / "background.py",
)
app_mod = load_module(
	f"{CHALLENGE_NAMESPACE}.plugin.application",
	ADDON_ROOT / "plugin" / "application.py",
)


class TestSlice8ThreadEliminationInvariants(unittest.TestCase):
	"""Challenge: Banned threads must never be spawned under any condition."""

	BANNED_THREAD_NAMES = frozenset({
		"litert-restart-on-config-change",
		"llama-shutdown-on-config-change",
		"LiteRTServerShutdown",
		"LlamaServerShutdown",
	})

	def setUp(self) -> None:
		self._spawned_threads: list[str] = []
		self._orig_thread_init = threading.Thread.__init__

		spawned = self._spawned_threads
		orig_init = self._orig_thread_init

		def patched_init(thread_self, *args, **kwargs):
			name = kwargs.get("name")
			if name:
				spawned.append(name)
			orig_init(thread_self, *args, **kwargs)

		self._thread_patch = patch.object(threading.Thread, "__init__", patched_init)
		self._thread_patch.start()

	def tearDown(self) -> None:
		self._thread_patch.stop()

	def _assert_no_banned_threads_spawned(self) -> None:
		banned_found = set(self._spawned_threads).intersection(self.BANNED_THREAD_NAMES)
		self.assertFalse(
			banned_found,
			f"Banned thread names were spawned: {banned_found}",
		)

	def test_config_change_notifications_do_not_spawn_banned_threads(self) -> None:
		"""Firing config change events in config.state never spawns restart/shutdown threads."""
		state_mod = load_module(
			f"{CHALLENGE_NAMESPACE}.config.state_real",
			ADDON_ROOT / "config" / "state.py",
		)
		# Fire config change notifications multiple times
		for _ in range(50):
			state_mod._notify_litert_server_config_changed()
			state_mod._notify_llama_server_config_changed()

		self._assert_no_banned_threads_spawned()

	def test_background_module_does_not_register_config_change_listeners(self) -> None:
		"""background.py does not contain or register config change listeners."""
		self.assertFalse(hasattr(bg_mod, "_on_litert_server_config_changed"))
		self.assertFalse(hasattr(bg_mod, "_restart_litert_server_worker"))
		self.assertFalse(hasattr(bg_mod, "_on_llama_server_config_changed"))

	def test_ensure_litert_server_ready_locked_completely_deleted(self) -> None:
		"""_ensure_litert_server_ready_locked alias must not exist."""
		self.assertFalse(hasattr(bg_mod, "_ensure_litert_server_ready_locked"))

	def test_ast_scan_application_and_background_for_banned_thread_names(self) -> None:
		"""AST verification across production files for banned thread names and signatures."""
		for file_name in ("background.py", "application.py"):
			file_path = ADDON_ROOT / "plugin" / file_name
			tree = ast.parse(file_path.read_text(encoding="utf-8"))

			# Inspect all string constants in AST
			constants = [
				node.value
				for node in ast.walk(tree)
				if isinstance(node, ast.Constant) and isinstance(node.value, str)
			]
			for banned in self.BANNED_THREAD_NAMES:
				self.assertNotIn(
					banned,
					constants,
					f"Found banned thread name '{banned}' in {file_name}",
				)

			# Ensure no function definitions for deleted functions
			func_defs = [
				node.name
				for node in ast.walk(tree)
				if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
			]
			self.assertNotIn("_ensure_litert_server_ready_locked", func_defs)
			self.assertNotIn("_on_litert_server_config_changed", func_defs)
			self.assertNotIn("_on_llama_server_config_changed", func_defs)
			self.assertNotIn("_restart_litert_server_worker", func_defs)

	def test_whole_addon_tree_free_of_deleted_shims(self) -> None:
		"""RS-10: Whole addon/ tree must be free of shadow test shims and deleted aliases."""
		for py_file in ADDON_ROOT.rglob("*.py"):
			content = py_file.read_text(encoding="utf-8")
			self.assertNotIn(
				"_TestShimSupervisor",
				content,
				f"_TestShimSupervisor still found in {py_file}",
			)
			self.assertNotIn(
				"_LlamaTestShimSupervisor",
				content,
				f"_LlamaTestShimSupervisor still found in {py_file}",
			)
			self.assertNotIn(
				"_ensure_litert_server_ready_locked",
				content,
				f"_ensure_litert_server_ready_locked still found in {py_file}",
			)


class TestApplicationTerminateConcurrencyStress(unittest.TestCase):
	"""Adversarially stress AIAssistantApplication.terminate() under active runtime conditions."""

	BANNED_THREAD_NAMES = frozenset({
		"litert-restart-on-config-change",
		"llama-shutdown-on-config-change",
		"LiteRTServerShutdown",
		"LlamaServerShutdown",
	})

	def setUp(self) -> None:
		self._spawned_threads: list[str] = []
		self._orig_thread_init = threading.Thread.__init__

		spawned = self._spawned_threads
		orig_init = self._orig_thread_init

		def patched_init(thread_self, *args, **kwargs):
			name = kwargs.get("name")
			if name:
				spawned.append(name)
			orig_init(thread_self, *args, **kwargs)

		self._thread_patch = patch.object(threading.Thread, "__init__", patched_init)
		self._thread_patch.start()

	def tearDown(self) -> None:
		self._thread_patch.stop()

	def _assert_no_banned_threads_spawned(self) -> None:
		banned_found = set(self._spawned_threads).intersection(self.BANNED_THREAD_NAMES)
		self.assertFalse(
			banned_found,
			f"Banned thread names were spawned: {banned_found}",
		)

	def test_real_application_terminate_spawns_zero_banned_threads(self) -> None:
		"""Real AIAssistantApplication class terminates without spawning any banned threads."""
		app = app_mod.AIAssistantApplication(host=MagicMock())
		app.terminate()
		self._assert_no_banned_threads_spawned()

	def test_real_application_terminate_under_high_concurrency_workers(self) -> None:
		"""Real AIAssistantApplication: terminate() called while multiple background workers are executing."""
		app = app_mod.AIAssistantApplication(host=MagicMock())

		started_event = threading.Event()
		worker_count = 15

		def slow_worker():
			started_event.wait(timeout=1.0)
			time.sleep(0.05)

		for i in range(worker_count):
			app.background._start_worker(target=slow_worker, name=f"ActiveWorker-{i}")

		# Trigger a model preload and provider state change concurrent with terminate
		app.background.start_model_preload()
		app._on_provider_state_change(types.SimpleNamespace(provider="litert-lm", model_name="m1", backend_url=""))

		started_event.set()

		# Call terminate() during peak concurrency
		t0 = time.perf_counter()
		app.terminate()
		duration = time.perf_counter() - t0

		# Assert non-blocking termination
		self.assertLess(duration, 0.5, f"terminate() took too long: {duration:.4f}s")
		self.assertTrue(app.background._closed.is_set())
		self._assert_no_banned_threads_spawned()

		# Verify subsequent background work is strictly rejected
		rejected = app.background._start_worker(target=lambda: None, name="RejectedWorker")
		self.assertFalse(rejected, "Background worker accepted after terminate()")

	def test_real_application_terminate_idempotence_and_concurrency(self) -> None:
		"""Real AIAssistantApplication: calling terminate() multiple times concurrently from 20 threads."""
		app = app_mod.AIAssistantApplication(host=MagicMock())

		errors: list[Exception] = []

		def concurrent_terminate():
			try:
				app.terminate()
			except Exception as exc:
				errors.append(exc)

		threads = [threading.Thread(target=concurrent_terminate) for _ in range(20)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=2.0)

		self.assertEqual(errors, [], f"Concurrent terminate() raised exceptions: {errors}")
		self.assertTrue(app.background._closed.is_set())
		self._assert_no_banned_threads_spawned()

	def test_real_application_terminate_suppresses_queued_results_during_active_work(self) -> None:
		"""Verify that in-flight workers whose execution finishes after terminate do not deliver to UI."""
		app = app_mod.AIAssistantApplication(host=MagicMock())

		delivered: list[object] = []
		blocker = threading.Event()

		def blocking_use_case():
			blocker.wait(timeout=2.0)
			return types.SimpleNamespace(message="done")

		app._services.use_case_engine.execute = lambda uid, progress=None: blocking_use_case()

		with patch.object(app_mod.nvda_ui, "queue", side_effect=lambda fn, res: delivered.append(res)):
			app.background.run_use_case_in_background(
				use_case_id="open-chat",
				title="Chat",
				render_result=lambda res: delivered.append(res),
			)

			# Give thread time to enter execute()
			time.sleep(0.05)

			# Terminate application while work is in flight
			app.terminate()

			# Unblock worker to finish
			blocker.set()

			# Wait for background thread pool to drain
			t0 = time.time()
			while time.time() - t0 < 1.0:
				with app.background._threads_lock:
					if not app.background._threads:
						break
				time.sleep(0.01)

		# No delivered results should have been queued
		self.assertEqual(delivered, [], "In-flight work delivered results after terminate() was called")
		self._assert_no_banned_threads_spawned()


class TestInvariantA14AdversarialValidation(unittest.TestCase):
	"""Invariant A14: Zero silent fallbacks and fail-closed validation on model resolution."""

	def test_unknown_model_names_fail_closed_without_mutation(self) -> None:
		adversarial_model_names = [
			"non-existent-model",
			"",
			"   ",
			"../../../evil/path",
			"model\r\n[injected_section]",
			"model\x00with_null",
			"llama-unknown-variant-999b",
		]

		for bad_name in adversarial_model_names:
			with self.subTest(model_name=bad_name):
				config = types.SimpleNamespace(
					provider="llama-cpp-server",
					model_name=bad_name,
				)
				mock_manager = MagicMock()
				mock_manager.find_record.return_value = None

				settings_sys_mod = sys.modules[f"{CHALLENGE_NAMESPACE}.config.settings"]
				mutated_models: list[str] = []

				with patch.object(bg_mod, "get_provider", return_value="llama-cpp-server"), \
					 patch.object(settings_sys_mod, "get_active_provider_config", return_value=config), \
					 patch.object(settings_sys_mod, "set_model_name", side_effect=mutated_models.append), \
					 patch.object(bg_mod, "LlamaCppModelManager", return_value=mock_manager):

					with self.assertRaises(bg_mod.LLMProviderError) as ctx:
						bg_mod.ensure_provider_server_ready()

					self.assertIn("Unknown llama.cpp model", str(ctx.exception))
					# Must never attempt to start server
					mock_manager.ensure_running.assert_not_called()
					# Must never silently mutate user settings
					self.assertEqual(mutated_models, [], "set_model_name was called during unknown model lookup")


if __name__ == "__main__":
	unittest.main()
