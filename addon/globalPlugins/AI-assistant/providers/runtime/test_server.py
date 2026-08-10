# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
"""Tests for LiteRTServerSupervisor delete_model and helpers."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
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


server_module = _load_module(
	f"{PACKAGE_NAME}.providers.runtime.server",
	MODULE_DIR / "server.py",
)

# Extract symbols under test
_build_delete_args = server_module._build_delete_args
LiteRTServerSupervisor = server_module.LiteRTServerSupervisor
LiteRTServerError = server_module.LiteRTServerError


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


if __name__ == "__main__":
	unittest.main()
