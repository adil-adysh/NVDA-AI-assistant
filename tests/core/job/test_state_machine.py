# -*- coding: utf-8 -*-
"""Unit tests for JobStateMachine and SessionStateMachine (Invariants A21, A23)."""

from __future__ import annotations

import unittest

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
state_mod = load_addon_module("core.job.state")

JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSpec = dto_mod.JobSpec
JobStatus = dto_mod.JobStatus
ModalityType = dto_mod.ModalityType
SessionConfig = dto_mod.SessionConfig
SessionState = dto_mod.SessionState

InvalidStateTransitionError = state_mod.InvalidStateTransitionError
JobStateMachine = state_mod.JobStateMachine
SessionStateMachine = state_mod.SessionStateMachine
TerminalStateError = state_mod.TerminalStateError


class TestJobStateMachineProgression(unittest.TestCase):
	"""Verify monotonic discrete job transitions, auto-advances, and terminal invariants."""

	def test_standard_happy_path_progression(self) -> None:
		spec = JobSpec(job_id="j1", job_type="model_download", payload={})
		fsm = JobStateMachine(spec)

		self.assertEqual(fsm.state, JobStatus.SUBMITTED)
		self.assertFalse(fsm.is_terminal)

		fsm.transition(JobStatus.QUEUED)
		self.assertEqual(fsm.state, JobStatus.QUEUED)
		self.assertFalse(fsm.is_terminal)

		fsm.transition(JobStatus.RUNNING)
		self.assertEqual(fsm.state, JobStatus.RUNNING)
		self.assertFalse(fsm.is_terminal)

		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=25.0)
		fsm.record_progress(prog)
		self.assertEqual(fsm.state, JobStatus.RUNNING)
		self.assertEqual(fsm.progress, prog)

		res = JobResult(job_id="j1", status=JobStatus.COMPLETED, result_data={"ok": True})
		fsm.record_result(res)
		self.assertEqual(fsm.state, JobStatus.COMPLETED)
		self.assertTrue(fsm.is_terminal)
		self.assertEqual(fsm.result, res)

	def test_short_circuit_cancellation_from_submitted(self) -> None:
		spec = JobSpec(job_id="j2", job_type="inference")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.CANCELLED)
		self.assertEqual(fsm.state, JobStatus.CANCELLED)
		self.assertTrue(fsm.is_terminal)

	def test_short_circuit_cancellation_from_queued(self) -> None:
		spec = JobSpec(job_id="j3", job_type="inference")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.QUEUED)
		fsm.transition(JobStatus.CANCELLED)
		self.assertEqual(fsm.state, JobStatus.CANCELLED)
		self.assertTrue(fsm.is_terminal)

	def test_short_circuit_failure_from_submitted(self) -> None:
		spec = JobSpec(job_id="j4", job_type="inference")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.FAILED)
		self.assertEqual(fsm.state, JobStatus.FAILED)
		self.assertTrue(fsm.is_terminal)

	def test_progress_auto_advances_from_submitted_and_queued(self) -> None:
		spec1 = JobSpec(job_id="j5", job_type="inference")
		fsm1 = JobStateMachine(spec1)
		fsm1.record_progress(JobProgress(job_id="j5", status=JobStatus.RUNNING, progress_pct=10.0))
		self.assertEqual(fsm1.state, JobStatus.RUNNING)

		spec2 = JobSpec(job_id="j6", job_type="inference")
		fsm2 = JobStateMachine(spec2)
		fsm2.transition(JobStatus.QUEUED)
		fsm2.record_progress(JobProgress(job_id="j6", status=JobStatus.RUNNING, progress_pct=10.0))
		self.assertEqual(fsm2.state, JobStatus.RUNNING)


class TestJobStateMachineViolations(unittest.TestCase):
	"""Verify illegal backward transitions and terminal immutability violations."""

	def test_backward_transitions_rejected(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.QUEUED)
		fsm.transition(JobStatus.RUNNING)

		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(JobStatus.QUEUED)

		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(JobStatus.SUBMITTED)

	def test_direct_jump_to_completed_from_submitted_rejected(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download")
		fsm = JobStateMachine(spec)

		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(JobStatus.COMPLETED)

	def test_terminal_immutability_enforced(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.RUNNING)
		fsm.transition(JobStatus.COMPLETED)

		# Any transition from completed must raise TerminalStateError
		with self.assertRaises(TerminalStateError):
			fsm.transition(JobStatus.RUNNING)

		with self.assertRaises(TerminalStateError):
			fsm.transition(JobStatus.FAILED)

		with self.assertRaises(TerminalStateError):
			fsm.record_progress(JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=100.0))

	def test_single_result_invariant(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.RUNNING)
		res1 = JobResult(job_id="j1", status=JobStatus.COMPLETED)
		fsm.record_result(res1)

		res2 = JobResult(job_id="j1", status=JobStatus.COMPLETED)
		with self.assertRaises(TerminalStateError) as ctx:
			fsm.record_result(res2)
		self.assertIn("single-result invariant", str(ctx.exception))

	def test_generation_fencing_rejects_stale_transitions(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download", generation=5)
		fsm = JobStateMachine(spec)

		# Stale transition generation
		with self.assertRaises(InvalidStateTransitionError) as ctx:
			fsm.transition(JobStatus.QUEUED, generation=4)
		self.assertIn("stale generation", str(ctx.exception))

		# Valid or incremented generation
		fsm.transition(JobStatus.QUEUED, generation=6)
		self.assertEqual(fsm.generation, 6)

		# Stale progress update rejected
		stale_prog = JobProgress(job_id="j1", status=JobStatus.RUNNING, generation=5)
		with self.assertRaises(InvalidStateTransitionError) as ctx2:
			fsm.record_progress(stale_prog)
		self.assertIn("Stale progress generation", str(ctx2.exception))

		# Stale result rejected
		fsm.transition(JobStatus.RUNNING)
		stale_res = JobResult(job_id="j1", status=JobStatus.COMPLETED, generation=5)
		with self.assertRaises(InvalidStateTransitionError) as ctx3:
			fsm.record_result(stale_res)
		self.assertIn("Stale result generation", str(ctx3.exception))

	def test_snapshot_preserves_state_and_history(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download")
		fsm = JobStateMachine(spec)
		fsm.transition(JobStatus.RUNNING)
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=50.0)
		fsm.record_progress(prog)

		snap = fsm.snapshot()
		self.assertEqual(snap.job_id, "j1")
		self.assertEqual(snap.state, JobStatus.RUNNING)
		self.assertEqual(snap.progress, prog)
		self.assertIsNone(snap.result)
		self.assertFalse(snap.is_terminal)


	def test_generation_not_modified_on_rejected_transition(self) -> None:
		"""Verify that generation is not modified when transition, progress, or result is rejected."""
		spec = JobSpec(job_id="j-gen-atom", job_type="test", generation=1)
		fsm = JobStateMachine(spec)

		# 1. Invalid backward transition with higher generation
		fsm.transition(JobStatus.RUNNING, generation=2)
		self.assertEqual(fsm.generation, 2)
		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(JobStatus.QUEUED, generation=99)
		self.assertEqual(fsm.generation, 2)

		# 2. Transition on terminal state with higher generation
		res = JobResult(job_id="j-gen-atom", status=JobStatus.COMPLETED, generation=2)
		fsm.record_result(res)
		self.assertTrue(fsm.is_terminal)

		with self.assertRaises(TerminalStateError):
			fsm.transition(JobStatus.RUNNING, generation=10)
		self.assertEqual(fsm.generation, 2)

		# 3. Progress on terminal state with higher generation
		with self.assertRaises(TerminalStateError):
			fsm.record_progress(
				JobProgress(job_id="j-gen-atom", status=JobStatus.RUNNING, generation=20)
			)
		self.assertEqual(fsm.generation, 2)

		# 4. Invalid result transition directly from SUBMITTED with higher generation
		spec2 = JobSpec(job_id="j-gen-atom2", job_type="test", generation=1)
		fsm2 = JobStateMachine(spec2)
		with self.assertRaises(InvalidStateTransitionError):
			fsm2.record_result(
				JobResult(job_id="j-gen-atom2", status=JobStatus.COMPLETED, generation=12)
			)
		self.assertEqual(fsm2.generation, 1)


class TestSessionStateMachine(unittest.TestCase):
	"""Verify continuous session FSM transitions and error states (Invariant A23)."""

	def test_session_lifecycle(self) -> None:
		cfg = SessionConfig(session_id="s1", modality=ModalityType.OCR)
		fsm = SessionStateMachine(cfg)
		self.assertEqual(fsm.state, SessionState.INIT)
		self.assertFalse(fsm.is_terminal)

		fsm.transition(SessionState.CONFIGURING)
		self.assertEqual(fsm.state, SessionState.CONFIGURING)

		fsm.transition(SessionState.READY)
		self.assertEqual(fsm.state, SessionState.READY)

		fsm.transition(SessionState.STREAMING)
		self.assertEqual(fsm.state, SessionState.STREAMING)

		# Self transition during streaming
		fsm.transition(SessionState.STREAMING)

		# Pause and resume
		fsm.transition(SessionState.PAUSED)
		self.assertEqual(fsm.state, SessionState.PAUSED)

		fsm.transition(SessionState.STREAMING)
		self.assertEqual(fsm.state, SessionState.STREAMING)

		# Closing and closed
		fsm.transition(SessionState.CLOSING)
		self.assertEqual(fsm.state, SessionState.CLOSING)

		fsm.transition(SessionState.CLOSED)
		self.assertEqual(fsm.state, SessionState.CLOSED)
		self.assertTrue(fsm.is_terminal)

	def test_session_terminal_immutability(self) -> None:
		cfg = SessionConfig(session_id="s2", modality=ModalityType.TRANSCRIPTION)
		fsm = SessionStateMachine(cfg)
		fsm.transition(SessionState.ERROR)
		self.assertTrue(fsm.is_terminal)

		with self.assertRaises(TerminalStateError):
			fsm.transition(SessionState.READY)

	def test_session_stale_generation_rejected(self) -> None:
		cfg = SessionConfig(session_id="s3", modality=ModalityType.OCR, generation=3)
		fsm = SessionStateMachine(cfg)

		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(SessionState.CONFIGURING, generation=2)

	def test_session_generation_not_modified_on_rejected_transition(self) -> None:
		"""Verify that session generation is not modified when transition fails validation."""
		cfg = SessionConfig(session_id="s-atom", modality=ModalityType.OCR, generation=1)
		fsm = SessionStateMachine(cfg)

		# 1. Invalid transition from INIT with higher generation
		with self.assertRaises(InvalidStateTransitionError):
			fsm.transition(SessionState.STREAMING, generation=10)
		self.assertEqual(fsm.generation, 1)

		# 2. Terminal state transition with higher generation
		fsm.transition(SessionState.CONFIGURING)
		fsm.transition(SessionState.ERROR)
		self.assertTrue(fsm.is_terminal)

		with self.assertRaises(TerminalStateError):
			fsm.transition(SessionState.READY, generation=15)
		self.assertEqual(fsm.generation, 1)


if __name__ == "__main__":
	unittest.main()
