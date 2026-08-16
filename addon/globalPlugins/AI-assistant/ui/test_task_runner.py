"""Regression tests for the UI/background task boundary."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import threading
import time
import types
import unittest


ROOT = Path(__file__).resolve().parent
MODULE_NAME = "task_runner_test_module"


def _load_runner():
	callbacks: list[object] = []
	wx_stub = types.ModuleType("wx")
	wx_stub.CallAfter = lambda callback: callbacks.append(callback)
	log_stub = types.ModuleType("logHandler")
	log_stub.log = types.SimpleNamespace(
		debug=lambda *args, **kwargs: None,
		error=lambda *args, **kwargs: None,
		exception=lambda *args, **kwargs: None,
	)
	sys.modules["wx"] = wx_stub
	sys.modules["logHandler"] = log_stub
	package_name = "task_runner_test_package"
	package = types.ModuleType(package_name)
	package.__path__ = [str(ROOT.parent)]
	ui_package = types.ModuleType(f"{package_name}.ui")
	ui_package.__path__ = [str(ROOT)]
	service_package = types.ModuleType(f"{package_name}.service")
	service_package.__path__ = [str(ROOT.parent / "service")]
	service_errors = types.ModuleType(f"{package_name}.service.error_reporter")
	service_errors.ErrorContext = lambda **kwargs: kwargs
	service_errors.ErrorReporter = object
	reported: list[tuple[object, object]] = []
	service_errors.error_reporter = types.SimpleNamespace(
		reported=reported,
		report=lambda error, context, **kwargs: reported.append((error, context)),
	)
	sys.modules[package_name] = package
	sys.modules[f"{package_name}.ui"] = ui_package
	sys.modules[f"{package_name}.service"] = service_package
	sys.modules[f"{package_name}.service.error_reporter"] = service_errors
	spec = spec_from_file_location(f"{package_name}.ui.task_runner", ROOT / "task_runner.py")
	assert spec is not None and spec.loader is not None
	module = module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module, callbacks


class BackgroundTaskRunnerTests(unittest.TestCase):
	def test_success_is_dispatched_and_work_runs_off_main_thread(self) -> None:
		runner_module, callbacks = _load_runner()
		runner = runner_module.BackgroundTaskRunner(max_workers=1)
		try:
			worker_thread: list[threading.Thread] = []
			results: list[int] = []
			handle = runner.submit(
				lambda _cancel: worker_thread.append(threading.current_thread()) or 42,
				on_success=results.append,
			)
			handle._future.result(timeout=2)
			for _ in range(20):
				if callbacks:
					break
				time.sleep(0.01)
			self.assertEqual(results, [])
			for callback in callbacks:
				callback()
			self.assertEqual(results, [42])
			self.assertIsNot(worker_thread[0], threading.main_thread())
		finally:
			runner._executor.shutdown(wait=True)

	def test_destroyed_owner_does_not_receive_callback(self) -> None:
		runner_module, callbacks = _load_runner()
		runner = runner_module.BackgroundTaskRunner(max_workers=1)
		try:
			results: list[int] = []
			handle = runner.submit(lambda _cancel: 1, on_success=results.append, is_alive=lambda: False)
			handle._future.result(timeout=2)
			for callback in callbacks:
				callback()
			self.assertEqual(results, [])
		finally:
			runner._executor.shutdown(wait=True)

	def test_failure_without_handler_is_reported(self) -> None:
		runner_module, callbacks = _load_runner()
		runner = runner_module.BackgroundTaskRunner(max_workers=1)
		try:
			handle = runner.submit(lambda _cancel: (_ for _ in ()).throw(RuntimeError("boom")))
			with self.assertRaises(RuntimeError):
				handle._future.result(timeout=2)
			for _ in range(20):
				if runner_module.error_reporter.reported:
					break
				time.sleep(0.01)
			self.assertEqual(len(runner_module.error_reporter.reported), 1)
		finally:
			runner._executor.shutdown(wait=True)


if __name__ == "__main__":
	unittest.main()
