"""Regression tests for the UI/background task boundary."""
from __future__ import annotations

from concurrent.futures import Future
from tests.support import ADDON_ROOT, load_module, register_package
import sys
import threading
import time
import types
import unittest
import importlib
from unittest import mock

import wx


ROOT = ADDON_ROOT / "ui"
MODULE_NAME = "task_runner_test_module"


def _load_runner():
	callbacks: list[object] = []
	package_name = "task_runner_test_package"
	register_package(package_name, ROOT.parent)
	register_package(f"{package_name}.ui", ROOT)
	register_package(f"{package_name}.service", ROOT.parent / "service")
	service_errors = types.ModuleType(f"{package_name}.service.error_reporter")
	service_errors.ErrorContext = lambda **kwargs: kwargs
	service_errors.ErrorReporter = object
	reported: list[tuple[object, object]] = []
	service_errors.error_reporter = types.SimpleNamespace(
		reported=reported,
		report=lambda error, context, **kwargs: reported.append((error, context)),
	)
	sys.modules[f"{package_name}.service.error_reporter"] = service_errors
	module = load_module(f"{package_name}.ui.task_runner", ROOT / "task_runner.py")
	return module, callbacks


class BackgroundTaskRunnerTests(unittest.TestCase):
	def test_diagnostic_writer_runs_file_work_on_its_own_thread(self) -> None:
		module, _callbacks = _load_runner()
		written = threading.Event()
		writer_threads = []
		writer = module._AsyncDiagnosticWriter(
			lambda _event: (writer_threads.append(threading.current_thread()), written.set())
		)
		writer.submit(object())
		self.assertTrue(written.wait(2))
		writer.flush()
		self.assertIsNot(writer_threads[0], threading.current_thread())

	def test_diagnostic_writer_exits_after_idle_period(self) -> None:
		module, _callbacks = _load_runner()
		written = threading.Event()
		writer = module._AsyncDiagnosticWriter(lambda _event: written.set())
		writer.IDLE_TIMEOUT = 0.02
		writer.submit(object())
		self.assertTrue(written.wait(2))
		writer.flush()
		thread = writer._thread
		deadline = time.monotonic() + 2
		while thread is not None and thread.is_alive() and time.monotonic() < deadline:
			time.sleep(0.01)
		self.assertFalse(thread and thread.is_alive())

	def test_submit_racing_idle_retirement_does_not_strand_event(self) -> None:
		module, _callbacks = _load_runner()
		written = []
		writer = module._AsyncDiagnosticWriter(written.append)
		writer.IDLE_TIMEOUT = 0.15
		writer.submit("warmup")
		writer.flush()
		original_put = writer._queue.put_nowait
		put_started = threading.Event()
		allow_put = threading.Event()
		def delayed_put(event):
			put_started.set()
			allow_put.wait(2)
			original_put(event)
		writer._queue.put_nowait = delayed_put
		submitter = threading.Thread(target=lambda: writer.submit("racing"))
		submitter.start()
		self.assertTrue(put_started.wait(2))
		time.sleep(0.2)
		allow_put.set()
		submitter.join(timeout=2)
		self.assertFalse(submitter.is_alive())
		self.assertIn("racing", written)

	def test_diagnostics_setting_is_checked_before_task_event_enqueue(self) -> None:
		module, _callbacks = _load_runner()
		settings = importlib.import_module("task_runner_test_package.config.settings")
		written = []
		writer = module._AsyncDiagnosticWriter(written.append)
		module._diagnostic_writer = writer
		with mock.patch.object(settings, "get_request_metrics_logging_enabled", return_value=False):
			self.assertFalse(module._diagnostics_logging_enabled())
			runner = module.BackgroundTaskRunner(max_workers=1)
			future = runner.submit(lambda _cancel: 1)
			future._future.result(timeout=2)
			runner._executor.shutdown(wait=True)
		writer.flush()
		self.assertEqual(written, [])

	def test_queued_cancellation_and_inline_completion_write_off_caller_thread(self) -> None:
		module, callbacks = _load_runner()
		written = []
		writer_threads = []
		writer = module._AsyncDiagnosticWriter(
			lambda event: (written.append(event.event), writer_threads.append(threading.current_thread()))
		)
		module._diagnostic_writer = writer
		module._diagnostics_logging_enabled = lambda: True
		with mock.patch.object(wx, "CallAfter", callbacks.append):
			runner = module.BackgroundTaskRunner(max_workers=1)
			gate = threading.Event()
			active = runner.submit(lambda _cancel: gate.wait(2) or 1)
			queued = runner.submit(lambda _cancel: 2)
			queued.cancel()
			self.assertTrue(queued._future.cancelled())
			gate.set()
			active._future.result(timeout=2)
			runner._executor.shutdown(wait=True)

			class ImmediateExecutor:
				def submit(self, work):
					future = Future()
					future.set_result(work())
					return future

			runner._executor = ImmediateExecutor()
			runner.submit(lambda _cancel: 3)
		writer.flush()
		self.assertIn("task_cancelled", written)
		self.assertIn("task_completed", written)
		self.assertTrue(writer_threads)
		self.assertTrue(all(thread is not threading.main_thread() for thread in writer_threads))

	def test_cancelled_failure_is_not_logged_as_error(self) -> None:
		module, callbacks = _load_runner()
		runner = module.BackgroundTaskRunner(max_workers=1)
		def stop(cancel):
			cancel.set()
			raise RuntimeError("Request stopped")
		with mock.patch.object(wx, "CallAfter", callbacks.append), mock.patch.object(module.log, "error") as errors:
			runner.submit(stop)
			runner._executor.shutdown(wait=True)
			for callback in callbacks:
				callback()
			errors.assert_not_called()

	def test_cancellation_suppresses_queued_result_but_runs_cleanup(self) -> None:
		module, callbacks = _load_runner()
		runner = module.BackgroundTaskRunner(max_workers=1)
		results = []
		cleaned = []
		with mock.patch.object(wx, "CallAfter", callbacks.append):
			handle = runner.submit(lambda _cancel: 42, on_success=results.append, on_finally=lambda: cleaned.append(True))
			runner._executor.shutdown(wait=True)
			handle.cancel()
			for callback in callbacks:
				callback()
		self.assertEqual(results, [])
		self.assertEqual(cleaned, [True])

	def test_failure_checks_owner_only_on_ui_thread(self) -> None:
		module, callbacks = _load_runner()
		gate = threading.Event()
		checks = []
		errors = []
		runner = module.BackgroundTaskRunner(max_workers=1)
		def fail(_cancel):
			gate.wait(2)
			raise RuntimeError("boom")
		with mock.patch.object(wx, "CallAfter", callbacks.append):
			handle = runner.submit(fail, on_error=errors.append, is_alive=lambda: checks.append(threading.current_thread()) or True)
			gate.set()
			runner._executor.shutdown(wait=True)
			self.assertTrue(handle.done)
			self.assertEqual(checks, [])
			for callback in callbacks:
				callback()
			self.assertEqual(checks, [threading.main_thread()])
			self.assertEqual(len(errors), 1)

	def test_success_is_dispatched_and_work_runs_off_main_thread(self) -> None:
		runner_module, callbacks = _load_runner()
		call_after_patch = mock.patch.object(wx, "CallAfter", lambda callback: callbacks.append(callback))
		call_after_patch.start()
		self.addCleanup(call_after_patch.stop)
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
		call_after_patch = mock.patch.object(wx, "CallAfter", lambda callback: callbacks.append(callback))
		call_after_patch.start()
		self.addCleanup(call_after_patch.stop)
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
		call_after_patch = mock.patch.object(wx, "CallAfter", lambda callback: callbacks.append(callback))
		call_after_patch.start()
		self.addCleanup(call_after_patch.stop)
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
