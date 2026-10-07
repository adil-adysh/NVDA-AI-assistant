# -*- coding: utf-8 -*-
"""Unit tests for CancellationToken and CancellationCoordinator (Invariant A22)."""

from __future__ import annotations

import time
import unittest

from tests.support import load_addon_module

cancel_mod = load_addon_module("core.job.cancellation")

CancellationCoordinator = cancel_mod.CancellationCoordinator
CancellationToken = cancel_mod.CancellationToken
JobCancelledError = cancel_mod.JobCancelledError
JobCancelledException = cancel_mod.JobCancelledException


class TestCancellationToken(unittest.TestCase):
	"""Verify cooperative cancellation token semantics and callbacks."""

	def test_token_lifecycle(self) -> None:
		token = CancellationToken("job-123")
		self.assertEqual(token.job_id, "job-123")
		self.assertFalse(token.is_cancelled)
		self.assertEqual(token.reason, "")
		self.assertEqual(token.cancelled_at_epoch_ms, 0)

		# Yield point does not raise when not cancelled
		token.check_cancelled()
		token.throw_if_cancelled()

		# Cancel token
		token.cancel("User aborted download")
		self.assertTrue(token.is_cancelled)
		self.assertEqual(token.reason, "User aborted download")
		self.assertGreater(token.cancelled_at_epoch_ms, 0)

		# Yield points now raise JobCancelledError
		with self.assertRaises(JobCancelledError) as ctx:
			token.check_cancelled()
		self.assertEqual(ctx.exception.job_id, "job-123")
		self.assertEqual(ctx.exception.reason, "User aborted download")

		with self.assertRaises(JobCancelledException):
			token.throw_if_cancelled()

		# Wait returns True immediately
		self.assertTrue(token.wait(timeout_seconds=0.1))

	def test_callbacks_fire_on_cancellation(self) -> None:
		token = CancellationToken("job-cb")
		fired = []

		def cb1() -> None:
			fired.append("cb1")

		def cb2() -> None:
			fired.append("cb2")

		def failing_cb() -> None:
			raise RuntimeError("Callback crash should not affect others")

		token.register_callback(cb1)
		token.register_callback(failing_cb)
		token.register_callback(cb2)

		self.assertEqual(fired, [])
		token.cancel("cancel with callbacks")

		self.assertIn("cb1", fired)
		self.assertIn("cb2", fired)

	def test_callback_registered_after_cancellation_fires_immediately(self) -> None:
		token = CancellationToken("job-late")
		token.cancel("already done")

		late_fired = []
		token.register_callback(lambda: late_fired.append("late"))
		self.assertEqual(late_fired, ["late"])


class TestCancellationCoordinator(unittest.TestCase):
	"""Verify two-phase cancellation coordination and preemption escalation."""

	def test_coordinator_token_management(self) -> None:
		coord = CancellationCoordinator()
		token = coord.register_token("job-1")
		self.assertIs(coord.get_token("job-1"), token)

		coord.unregister_token("job-1")
		self.assertIsNone(coord.get_token("job-1"))

	def test_two_phase_preemption_escalation(self) -> None:
		coord = CancellationCoordinator()
		token = coord.register_token("job-heavy")

		# Non-existent job cancellation returns False
		self.assertFalse(coord.request_cancellation("non-existent-job"))

		# Phase 1 request
		success = coord.request_cancellation(
			"job-heavy",
			reason="User pressed Escape",
			preemption_timeout=0.05,  # 50ms for fast unit test
		)
		self.assertTrue(success)
		self.assertTrue(token.is_cancelled)
		self.assertEqual(token.reason, "User pressed Escape")

		# Preemption not due yet immediately
		self.assertFalse(coord.is_preemption_due("job-heavy"))
		deadline = coord.get_preemption_deadline("job-heavy")
		self.assertIsNotNone(deadline)

		# Wait for preemption deadline to expire
		time.sleep(0.06)
		self.assertTrue(coord.is_preemption_due("job-heavy"))

	def test_cancel_all(self) -> None:
		coord = CancellationCoordinator()
		t1 = coord.register_token("j1")
		t2 = coord.register_token("j2")

		coord.cancel_all(reason="NVDA exit")
		self.assertTrue(t1.is_cancelled)
		self.assertEqual(t1.reason, "NVDA exit")
		self.assertTrue(t2.is_cancelled)
		self.assertEqual(t2.reason, "NVDA exit")

	def test_reentrant_callback_does_not_deadlock(self) -> None:
		"""Verify that a callback invoking coordinator methods during cancellation completes without deadlock."""
		import threading

		coord = CancellationCoordinator()
		token = coord.register_token("job-reentrant")
		queries_succeeded = []

		def reentrant_callback() -> None:
			t = coord.get_token("job-reentrant")
			is_due = coord.is_preemption_due("job-reentrant")
			deadline = coord.get_preemption_deadline("job-reentrant")
			if t is not None and not is_due and deadline is not None:
				queries_succeeded.append(True)

		token.register_callback(reentrant_callback)

		result = []

		def run() -> None:
			result.append(coord.request_cancellation("job-reentrant", reason="test_reentrant"))

		t = threading.Thread(target=run)
		t.start()
		t.join(timeout=1.0)
		self.assertFalse(t.is_alive(), "request_cancellation deadlocked with re-entrant callback")
		self.assertEqual(result, [True])
		self.assertEqual(queries_succeeded, [True])


if __name__ == "__main__":
	unittest.main()
