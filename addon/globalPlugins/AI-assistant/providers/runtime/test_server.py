# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
"""Tests for LiteRTServerSupervisor delete_model and helpers."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "runtime_server_testpkg"

# ── NVDA stubs ────────────────────────────────────────────────────
log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(
	debug=lambda *args, **kwargs: None,
	info=lambda *args, **kwargs: None,
	warning=lambda *args, **kwargs: None,
	exception=lambda *args, **kwargs: None,
)
sys.modules["logHandler"] = log_handler_module

# ── Load the server module ────────────────────────────────────────
# We must register a synthetic package so intra-package imports resolve.
_register_package = types.ModuleType(PACKAGE_NAME)
_register_package.__path__ = [str(ROOT_DIR)]
sys.modules[PACKAGE_NAME] = _register_package

runtime_pkg = types.ModuleType(f"{PACKAGE_NAME}.providers")
runtime_pkg.__path__ = [str(ROOT_DIR / "..")]
sys.modules[f"{PACKAGE_NAME}.providers"] = runtime_pkg

runtime_mod = types.ModuleType(f"{PACKAGE_NAME}.providers.runtime")
runtime_mod.__path__ = [str(MODULE_DIR)]
sys.modules[f"{PACKAGE_NAME}.providers.runtime"] = runtime_mod

# Stub submodules that server.py imports from
runtime_config = types.ModuleType(f"{PACKAGE_NAME}.providers.runtime.config")
runtime_config.RuntimeConfig = mock.MagicMock()
sys.modules[runtime_config.__name__] = runtime_config

runtime_download = types.ModuleType(f"{PACKAGE_NAME}.providers.runtime.download")
runtime_download.DownloadCancelledError = type("DownloadCancelledError", (Exception,), {})
runtime_download.RuntimeDownloadService = mock.MagicMock()
sys.modules[runtime_download.__name__] = runtime_download

runtime_paths = types.ModuleType(f"{PACKAGE_NAME}.providers.runtime.paths")
runtime_paths.get_runtime_path = mock.MagicMock(return_value=Path("/fake/runtime"))
sys.modules[runtime_paths.__name__] = runtime_paths

# Stub the interfaces module
interfaces_mod = types.ModuleType(f"{PACKAGE_NAME}.providers.interfaces")
interfaces_mod.LLMProviderError = type("LLMProviderError", (Exception,), {})
interfaces_mod.ProgressCallback = None
sys.modules[interfaces_mod.__name__] = interfaces_mod


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


# Register the config package so config.model_config (used by
# build_server_config) can be loaded for constructing ModelSamplingConfig.
config_dir = ROOT_DIR.parent / "config"
config_pkg = types.ModuleType(f"{PACKAGE_NAME}.config")
config_pkg.__path__ = [str(config_dir)]
sys.modules[f"{PACKAGE_NAME}.config"] = config_pkg

_load_module(f"{PACKAGE_NAME}.config.defaults", config_dir / "defaults.py")
_load_module(
	f"{PACKAGE_NAME}.config.model_config",
	config_dir / "model_config.py",
)

server_module = _load_module(
	f"{PACKAGE_NAME}.providers.runtime.server",
	MODULE_DIR / "server.py",
)

# Extract symbols under test
_build_delete_args = server_module._build_delete_args
LiteRTServerSupervisor = server_module.LiteRTServerSupervisor
LiteRTServerError = server_module.LiteRTServerError

ModelSamplingConfig = sys.modules[
	f"{PACKAGE_NAME}.config.model_config"
].ModelSamplingConfig


def _pinned(**kwargs) -> ModelSamplingConfig:
	"""Build a ModelSamplingConfig with the given explicit pins."""
	return ModelSamplingConfig(**kwargs)


class BuildServerConfigTests(unittest.TestCase):
	"""Tests for build_server_config — the pure config.json payload builder."""

	def test_default_only_when_no_pin(self) -> None:
		config = server_module.build_server_config(16384, {})
		self.assertEqual(config, {"default": {"max_num_tokens": 16384}})

	def test_per_model_override_when_pin_differs(self) -> None:
		config = server_module.build_server_config(
			8192,
			{
				"litert-community/gemma-4-E2B-it-litert-lm-gpu": _pinned(
					num_ctx=32768
				)
			},
		)
		self.assertEqual(
			config,
			{
				"default": {"max_num_tokens": 8192},
				"models": {
					"litert-community/gemma-4-E2B-it-litert-lm-gpu": {
						"max_num_tokens": 32768,
					},
				},
			},
		)

	def test_no_per_model_override_when_pin_matches_default(self) -> None:
		config = server_module.build_server_config(
			8192,
			{"model-x": _pinned(num_ctx=8192)},
		)
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})

	def test_emits_multiple_pinned_models(self) -> None:
		"""Pins for every model are emitted, not just an active one."""
		config = server_module.build_server_config(
			8192,
			{
				"model-a": _pinned(num_ctx=32768),
				"model-b": _pinned(temperature=0.5),
			},
		)
		self.assertEqual(
			config,
			{
				"default": {"max_num_tokens": 8192},
				"models": {
					"model-a": {"max_num_tokens": 32768},
					"model-b": {"temperature": 0.5},
				},
			},
		)

	def test_empty_when_default_is_zero(self) -> None:
		config = server_module.build_server_config(0, {})
		self.assertEqual(config, {})

	def test_emits_backend_when_provided(self) -> None:
		config = server_module.build_server_config(8192, {}, backend="gpu")
		self.assertEqual(
			config,
			{"default": {"max_num_tokens": 8192, "backend": "gpu"}},
		)

	def test_emits_cache_and_cpu_threads_when_provided(self) -> None:
		config = server_module.build_server_config(
			16384,
			{},
			cache="memory",
			cpu_thread_count=4,
		)
		self.assertEqual(
			config,
			{
				"default": {
					"max_num_tokens": 16384,
					"cache": "memory",
					"cpu_thread_count": 4,
				},
			},
		)

	def test_omits_engine_knobs_by_default(self) -> None:
		config = server_module.build_server_config(8192, {})
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})

	def test_omits_engine_knobs_when_explicitly_default(self) -> None:
		"""Empty backend/cache/zero threads ("default") are not written."""
		config = server_module.build_server_config(
			8192,
			{},
			backend="",
			cache="",
			cpu_thread_count=0,
		)
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})

	def test_ignores_zero_cpu_threads(self) -> None:
		config = server_module.build_server_config(
			8192,
			{},
			cpu_thread_count=0,
		)
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})

	def test_emits_pinned_sampling_with_num_ctx(self) -> None:
		config = server_module.build_server_config(
			8192,
			{"model-x": _pinned(num_ctx=32768, temperature=0.7, top_k=40, top_p=0.9)},
		)
		self.assertEqual(
			config,
			{
				"default": {"max_num_tokens": 8192},
				"models": {
					"model-x": {
						"max_num_tokens": 32768,
						"temperature": 0.7,
						"top_k": 40,
						"top_p": 0.9,
					},
				},
			},
		)

	def test_emits_sampling_without_num_ctx_pin(self) -> None:
		"""Sampling pins alone still produce a models.<id> section."""
		config = server_module.build_server_config(
			8192,
			{"model-x": _pinned(temperature=0.5)},
		)
		self.assertEqual(
			config,
			{
				"default": {"max_num_tokens": 8192},
				"models": {"model-x": {"temperature": 0.5}},
			},
		)

	def test_omits_unpinned_sampling(self) -> None:
		config = server_module.build_server_config(
			8192,
			{"model-x": _pinned(num_ctx=32768)},
		)
		self.assertEqual(
			config,
			{
				"default": {"max_num_tokens": 8192},
				"models": {"model-x": {"max_num_tokens": 32768}},
			},
		)

	def test_omits_out_of_range_sampling(self) -> None:
		"""Schema-invalid sampling values never reach config.json."""
		config = server_module.build_server_config(
			8192,
			{
				"model-x": _pinned(
					temperature=-0.5,
					top_k=0,
					top_p=1.5,
				)
			},
		)
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})

	def test_unsupported_sampling_keys_omitted(self) -> None:
		"""max_tokens/repeat_penalty have no litert-lm config key."""
		config = server_module.build_server_config(
			8192,
			{"model-x": _pinned(max_tokens=2048, repeat_penalty=1.1)},
		)
		self.assertEqual(config, {"default": {"max_num_tokens": 8192}})


class BuildDeleteArgsTests(unittest.TestCase):
	"""Tests for _build_delete_args — pure function, no mocking needed."""

	def test_builds_delete_command_with_model_id(self) -> None:
		args = _build_delete_args("litert-community/gemma-4-E2B-it-litert-lm")
		self.assertEqual(args, ["delete", "litert-community/gemma-4-E2B-it-litert-lm"])

	def test_handles_simple_model_id(self) -> None:
		args = _build_delete_args("test-model")
		self.assertEqual(args, ["delete", "test-model"])

	def test_handles_empty_model_id(self) -> None:
		# The CLI will handle validation; the helper just passes through.
		args = _build_delete_args("")
		self.assertEqual(args, ["delete", ""])


class SupervisorDeleteModelTests(unittest.TestCase):
	"""Tests for LiteRTServerSupervisor.delete_model."""

	def setUp(self) -> None:
		self._resolve_patcher = mock.patch.object(
			server_module,
			"_resolve_litert_python",
			return_value=Path("/fake/runtime/python.exe"),
		)
		self._run_cli_patcher = mock.patch.object(
			server_module,
			"_run_litert_cli",
		)
		self.mock_resolve = self._resolve_patcher.start()
		self.mock_run_cli = self._run_cli_patcher.start()

		# Create supervisor with fake internals
		self.supervisor = LiteRTServerSupervisor()
		# Replace server dir/path resolution with a fixed path
		self.supervisor._server_dir = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime")
		)
		self.supervisor._server_python = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime/python.exe"),
		)

	def tearDown(self) -> None:
		self._resolve_patcher.stop()
		self._run_cli_patcher.stop()

	# ── Normal deletion ──────────────────────────────────────────

	def test_delete_succeeds_with_returncode_zero(self) -> None:
		"""Model deletion returns exit code 0."""
		self.mock_run_cli.return_value = subprocess.CompletedProcess(
			args=["python", "-m", "litert_lm_cli.main", "delete", "test-model"],
			returncode=0,
			stdout="",
			stderr="",
		)

		self.supervisor.delete_model("test-model")

		self.mock_run_cli.assert_called_once()
		call_args, call_kwargs = self.mock_run_cli.call_args
		self.assertEqual(call_args[1], ["delete", "test-model"])
		self.assertEqual(call_kwargs["timeout"], 60)
		self.assertTrue(call_kwargs["capture"])
		self.assertIn("LITERT_LM_DIR", call_kwargs["env"])

	# ── Idempotent: already-absent model ─────────────────────────

	def test_delete_idempotent_already_absent(self) -> None:
		"""CLI returns 0 and 'Model not found' for absent models."""
		self.mock_run_cli.return_value = subprocess.CompletedProcess(
			args=["python", "-m", "litert_lm_cli.main", "delete", "absent-model"],
			returncode=0,
			stdout="Model not found: absent-model\n",
			stderr="",
		)

		# Should not raise — CLI treats "not found" as success.
		self.supervisor.delete_model("absent-model")

	# ── Failure: non-zero exit code ──────────────────────────────

	def test_delete_raises_on_nonzero_returncode(self) -> None:
		"""Non-zero exit code must raise LiteRTServerError."""
		self.mock_run_cli.return_value = subprocess.CompletedProcess(
			args=["python", "-m", "litert_lm_cli.main", "delete", "locked-model"],
			returncode=1,
			stdout="",
			stderr="Error: model is locked\n",
		)

		with self.assertRaises(LiteRTServerError) as ctx:
			self.supervisor.delete_model("locked-model")
		self.assertIn("locked-model", str(ctx.exception))
		self.assertIn("Error: model is locked", str(ctx.exception))

	# ── Failure: invalid model ID ────────────────────────────────

	def test_delete_raises_on_invalid_model_id(self) -> None:
		"""Invalid model IDs must be caught before CLI invocation."""
		invalid_ids = [
			("", "empty string"),
			("path\\traversal", "backslash"),
			("../escape", "parent dir"),
			("has\x00null", "null byte"),
		]

		for model_id, case_name in invalid_ids:
			with self.subTest(case=case_name, model_id=model_id):
				with self.assertRaises(LiteRTServerError):
					self.supervisor.delete_model(model_id)
				self.mock_run_cli.assert_not_called()

	# ── Failure: timeout ─────────────────────────────────────────

	def test_delete_raises_on_timeout(self) -> None:
		"""Timeout must raise LiteRTServerError."""
		self.mock_run_cli.side_effect = subprocess.TimeoutExpired(
			cmd=["delete", "slow-model"],
			timeout=60,
		)

		with self.assertRaises(LiteRTServerError) as ctx:
			self.supervisor.delete_model("slow-model")
		self.assertIn("timed out", str(ctx.exception))

	# ── LITERT_LM_DIR is correct ─────────────────────────────────

	def test_delete_uses_correct_litert_lm_dir(self) -> None:
		"""The delete command must use the same LITERT_LM_DIR as import/serve."""
		self.mock_run_cli.return_value = subprocess.CompletedProcess(
			args=[],
			returncode=0,
			stdout="",
			stderr="",
		)

		self.supervisor.delete_model("test-model")

		_, call_kwargs = self.mock_run_cli.call_args
		env = call_kwargs["env"]
		self.assertIn("LITERT_LM_DIR", env)
		litert_dir = str(env["LITERT_LM_DIR"])
		self.assertIn("nvda", litert_dir)
		self.assertIn("AIAssistant", litert_dir)
		self.assertIn("litert-lm", litert_dir)


class SupervisorStartConfigTests(unittest.TestCase):
	"""Tests that start() writes config.json before spawning the server."""

	def setUp(self) -> None:
		self._resolve_patcher = mock.patch.object(
			server_module,
			"_resolve_litert_python",
			return_value=Path("/fake/runtime/python.exe"),
		)
		self._run_cli_patcher = mock.patch.object(
			server_module,
			"_run_litert_cli",
			return_value=mock.MagicMock(pid=4242, poll=lambda: None),
		)
		self._config_patcher = mock.patch.object(
			server_module,
			"_current_server_config",
			return_value={
				"default": {"max_num_tokens": 16384},
				"models": {"gemma-e2b": {"max_num_tokens": 32768}},
			},
		)
		self.mock_resolve = self._resolve_patcher.start()
		self.mock_run_cli = self._run_cli_patcher.start()
		self.mock_config = self._config_patcher.start()

		self._tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self._tmp.cleanup)
		self._litert_dir_patcher = mock.patch.object(
			server_module,
			"_default_litert_dir",
			return_value=Path(self._tmp.name),
		)
		self._litert_dir_patcher.start()
		self.addCleanup(self._litert_dir_patcher.stop)

		self.supervisor = LiteRTServerSupervisor()
		self.supervisor._server_dir = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime"),
		)
		self.supervisor._server_python = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime/python.exe"),
		)

	def tearDown(self) -> None:
		self._resolve_patcher.stop()
		self._run_cli_patcher.stop()
		self._config_patcher.stop()

	def test_start_writes_config_json_before_serve(self) -> None:
		"""config.json must be written with max_num_tokens before spawning."""
		self.supervisor.start()

		config_path = Path(self._tmp.name) / "config.json"
		self.assertTrue(config_path.is_file())
		data = json.loads(config_path.read_text(encoding="utf-8"))
		self.assertEqual(data["default"]["max_num_tokens"], 16384)
		self.assertEqual(data["models"]["gemma-e2b"]["max_num_tokens"], 32768)

		call_args, _ = self.mock_run_cli.call_args
		self.assertEqual(
			call_args[1],
			["serve", "--host", "127.0.0.1", "--port", "9379"],
		)
		self.assertIn("LITERT_LM_DIR", self.mock_run_cli.call_args.kwargs["env"])

	def test_start_skips_config_json_when_empty(self) -> None:
		"""No config.json when there is nothing to configure."""
		self.mock_config.return_value = {}

		self.supervisor.start()

		config_path = Path(self._tmp.name) / "config.json"
		self.assertFalse(config_path.is_file())
		self.mock_run_cli.assert_called_once()

	def test_start_removes_stale_config_when_empty(self) -> None:
		"""An empty payload removes any stale config.json from a prior run."""
		config_path = Path(self._tmp.name) / "config.json"
		config_path.parent.mkdir(parents=True, exist_ok=True)
		config_path.write_text(
			json.dumps({"default": {"max_num_tokens": 8192}}),
			encoding="utf-8",
		)

		self.mock_config.return_value = {}
		self.supervisor.start()

		self.assertFalse(config_path.is_file())

	def test_start_writes_engine_knobs(self) -> None:
		"""config.json carries backend/cache/cpu_thread_count when configured."""
		self.mock_config.return_value = {
			"default": {
				"max_num_tokens": 16384,
				"backend": "gpu",
				"cpu_thread_count": 4,
			},
		}

		self.supervisor.start()

		config_path = Path(self._tmp.name) / "config.json"
		data = json.loads(config_path.read_text(encoding="utf-8"))
		self.assertEqual(data["default"]["backend"], "gpu")
		self.assertEqual(data["default"]["cpu_thread_count"], 4)
		self.mock_run_cli.assert_called_once()


class SupervisorRestartTests(unittest.TestCase):
	"""Tests for LiteRTServerSupervisor.restart — stop + start with fresh config."""

	def setUp(self) -> None:
		self._resolve_patcher = mock.patch.object(
			server_module,
			"_resolve_litert_python",
			return_value=Path("/fake/runtime/python.exe"),
		)
		self._run_cli_patcher = mock.patch.object(
			server_module,
			"_run_litert_cli",
			return_value=mock.MagicMock(pid=4242, poll=lambda: None),
		)
		self._config_patcher = mock.patch.object(
			server_module,
			"_current_server_config",
			return_value={"default": {"max_num_tokens": 8192}},
		)
		self.mock_resolve = self._resolve_patcher.start()
		self.mock_run_cli = self._run_cli_patcher.start()
		self.mock_config = self._config_patcher.start()

		self._tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self._tmp.cleanup)
		self._litert_dir_patcher = mock.patch.object(
			server_module,
			"_default_litert_dir",
			return_value=Path(self._tmp.name),
		)
		self._litert_dir_patcher.start()
		self.addCleanup(self._litert_dir_patcher.stop)

		self.supervisor = LiteRTServerSupervisor()
		self.supervisor._server_dir = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime"),
		)
		self.supervisor._server_python = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime/python.exe"),
		)

	def tearDown(self) -> None:
		self._resolve_patcher.stop()
		self._run_cli_patcher.stop()
		self._config_patcher.stop()

	def test_restart_regenerates_config_and_respawns(self) -> None:
		"""restart() stops and starts, regenerating config.json from settings."""
		self.supervisor.start()
		self.assertEqual(self.mock_run_cli.call_count, 1)

		self.supervisor.restart()

		self.assertEqual(self.mock_run_cli.call_count, 2)
		config_path = Path(self._tmp.name) / "config.json"
		data = json.loads(config_path.read_text(encoding="utf-8"))
		self.assertEqual(data["default"]["max_num_tokens"], 8192)

	def test_restart_when_not_running_starts(self) -> None:
		"""restart() with no running server just starts it with fresh config."""
		self.supervisor.restart()

		self.assertEqual(self.mock_run_cli.call_count, 1)
		config_path = Path(self._tmp.name) / "config.json"
		self.assertTrue(config_path.is_file())


class SupervisorHostPortTests(unittest.TestCase):
	"""Tests for _effective_host_port resolving the configured server URL."""

	def setUp(self) -> None:
		self.supervisor = LiteRTServerSupervisor()
		self._settings_mod = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
		self._settings_mod.get_litert_server_url = mock.MagicMock()
		sys.modules[self._settings_mod.__name__] = self._settings_mod
		self.addCleanup(sys.modules.pop, self._settings_mod.__name__, None)

	def test_uses_configured_url_host_and_port(self) -> None:
		"""A configured URL with a port drives the bind address."""
		self._settings_mod.get_litert_server_url.return_value = (
			"http://127.0.0.1:9555"
		)
		self.assertEqual(
			self.supervisor._effective_host_port(),  # pylint: disable=protected-access
			("127.0.0.1", 9555),
		)

	def test_falls_back_to_defaults_when_no_port(self) -> None:
		"""A URL without a port keeps the constructor-provided defaults."""
		self._settings_mod.get_litert_server_url.return_value = "http://127.0.0.1"
		self.assertEqual(
			self.supervisor._effective_host_port(),  # pylint: disable=protected-access
			("127.0.0.1", 9379),
		)

	def test_falls_back_to_defaults_when_settings_raise(self) -> None:
		"""A failing settings read must not break server startup."""
		self._settings_mod.get_litert_server_url.side_effect = RuntimeError("boom")
		self.assertEqual(
			self.supervisor._effective_host_port(),  # pylint: disable=protected-access
			("127.0.0.1", 9379),
		)


class AdoptStateTests(unittest.TestCase):
	"""Tests for the adopted-server state consumed by readiness evaluation."""

	def test_not_adopted_initially(self) -> None:
		supervisor = LiteRTServerSupervisor()
		self.assertFalse(supervisor.is_adopted)
		self.assertFalse(supervisor.is_running)

	def test_adopt_marks_adopted_without_handle(self) -> None:
		supervisor = LiteRTServerSupervisor()
		supervisor.adopt()
		self.assertTrue(supervisor.is_adopted)
		self.assertFalse(supervisor.is_running)

	def test_adopt_ignored_when_process_running(self) -> None:
		supervisor = LiteRTServerSupervisor()
		supervisor._process = mock.MagicMock(  # pylint: disable=protected-access
			pid=123, poll=lambda: None
		)
		supervisor.adopt()
		self.assertFalse(supervisor.is_adopted)
		self.assertTrue(supervisor.is_running)

	def test_start_clears_adopted_state(self) -> None:
		supervisor = LiteRTServerSupervisor()
		supervisor._adopted = True  # pylint: disable=protected-access
		supervisor._server_dir = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime"),
		)
		supervisor._server_python = mock.MagicMock(  # pylint: disable=protected-access
			return_value=Path("/fake/runtime/python.exe"),
		)
		with mock.patch.object(
			server_module, "_resolve_litert_python",
			return_value=Path("/fake/runtime/python.exe"),
		), mock.patch.object(
			server_module, "_run_litert_cli",
			return_value=mock.MagicMock(pid=123, poll=lambda: None),
		), mock.patch.object(
			server_module, "_current_server_config", return_value={},
		), mock.patch.object(
			server_module, "_default_litert_dir",
			return_value=Path(tempfile.gettempdir()),
		):
			supervisor.start()

		self.assertTrue(supervisor.is_running)
		self.assertFalse(supervisor.is_adopted)

	def test_stop_clears_adopted_state(self) -> None:
		supervisor = LiteRTServerSupervisor()
		process = mock.MagicMock(pid=123)
		process.poll.return_value = None
		process.wait.return_value = 0
		supervisor._process = process  # pylint: disable=protected-access
		supervisor._adopted = True  # pylint: disable=protected-access

		supervisor.stop()

		self.assertFalse(supervisor.is_adopted)
		self.assertFalse(supervisor.is_running)


if __name__ == "__main__":
	unittest.main()
