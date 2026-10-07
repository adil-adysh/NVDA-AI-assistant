# -*- coding: utf-8 -*-
"""Unit tests for Windows Job Object Containment (Invariants A16, A26)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

from tests.support import load_addon_module

job_mod = load_addon_module("worker.job_object")

CtypesJobObject = job_mod.CtypesJobObject
JobObject = job_mod.JobObject
PyWin32JobObject = job_mod.PyWin32JobObject
assign_process_to_job = job_mod.assign_process_to_job
create_worker_job_object = job_mod.create_worker_job_object
is_job_object_supported = job_mod.is_job_object_supported


class TestJobObjectContainment(unittest.TestCase):
	"""Verify Windows Job Object creation, limits, and process assignment."""

	def setUp(self) -> None:
		if not is_job_object_supported():
			self.skipTest("Job Objects require Windows platform")

	def test_create_worker_job_object(self) -> None:
		"""Verify standard factory creates a valid JobObject."""
		job = create_worker_job_object()
		try:
			self.assertTrue(job.is_valid)
		finally:
			job.close()
			self.assertFalse(job.is_valid)

	def test_job_object_context_manager(self) -> None:
		"""Verify JobObject supports context manager protocol."""
		with create_worker_job_object() as job:
			self.assertTrue(job.is_valid)
		self.assertFalse(job.is_valid)

	def test_pywin32_job_object_limits(self) -> None:
		"""Verify PyWin32JobObject sets KILL_ON_JOB_CLOSE and DIE_ON_UNHANDLED_EXCEPTION."""
		try:
			import win32job
		except ImportError:
			self.skipTest("pywin32 not available")

		job = PyWin32JobObject()
		try:
			self.assertTrue(job.is_valid)
			info = win32job.QueryInformationJobObject(
				job._handle, win32job.JobObjectExtendedLimitInformation
			)
			flags = info["BasicLimitInformation"]["LimitFlags"]
			expected_flags = (
				job_mod.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
				| job_mod.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
			)
			self.assertEqual(flags & expected_flags, expected_flags)
		finally:
			job.close()

	def test_ctypes_job_object_limits(self) -> None:
		"""Verify CtypesJobObject sets limits properly via ctypes."""
		job = CtypesJobObject()
		try:
			self.assertTrue(job.is_valid)
		finally:
			job.close()
			self.assertFalse(job.is_valid)

	def test_assign_process_to_job(self) -> None:
		"""Verify subprocess can be assigned to job object via Popen handle."""
		job = create_worker_job_object()
		proc = subprocess.Popen(
			[sys.executable, "-c", "import time; time.sleep(5)"],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		try:
			assign_process_to_job(job, proc)
			# Verify process is running
			self.assertIsNone(proc.poll())
		finally:
			proc.terminate()
			proc.wait()
			job.close()

	def test_assign_process_by_integer_handle(self) -> None:
		"""Verify process can be assigned using integer handle value."""
		job = create_worker_job_object()
		proc = subprocess.Popen(
			[sys.executable, "-c", "import time; time.sleep(5)"],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		try:
			handle_int = int(proc._handle)
			job.assign_process(handle_int)
			self.assertIsNone(proc.poll())
		finally:
			proc.terminate()
			proc.wait()
			job.close()

	def test_assign_to_closed_job_raises_error(self) -> None:
		"""Verify assigning to a closed job object raises an OSError."""
		job = create_worker_job_object()
		job.close()
		with self.assertRaises(OSError):
			job.assign_process(12345)

	def test_child_process_killed_on_parent_exit(self) -> None:
		"""Verify child process assigned to job object with KILL_ON_JOB_CLOSE terminates when job closes."""
		# Launch a script that creates a job object, spawns a child process, assigns child to job,
		# and then exits immediately.
		script = (
			"import subprocess, sys, time, os\n"
			"from tests.support import load_addon_module\n"
			"job_mod = load_addon_module('worker.job_object')\n"
			"job = job_mod.create_worker_job_object()\n"
			"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
			"job.assign_process(child)\n"
			"print(child.pid, flush=True)\n"
			"os._exit(0)\n"  # Hard exit closing all handles
		)

		proc = subprocess.Popen(
			[sys.executable, "-c", script],
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
		)
		stdout, _ = proc.communicate(timeout=5.0)
		child_pid = int(stdout.strip())

		# Give OS kernel up to 1 second to clean up the process tree
		deadline = time.time() + 1.0
		child_is_dead = False
		while time.time() < deadline:
			try:
				# On Windows, os.kill(pid, 0) checks if process exists
				os.kill(child_pid, 0)
				time.sleep(0.05)
			except OSError:
				child_is_dead = True
				break

		self.assertTrue(
			child_is_dead,
			f"Child process {child_pid} was not killed by Windows Job Object on parent exit",
		)


if __name__ == "__main__":
	unittest.main()
