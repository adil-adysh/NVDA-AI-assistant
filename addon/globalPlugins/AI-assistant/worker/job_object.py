# -*- coding: utf-8 -*-
"""Windows Job Object Containment for Subprocess Lifetime Isolation.

Enforces Invariant A16 and Invariant A26:
All worker and spawned server processes are assigned to a Windows Job Object configured
with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) and
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION (0x0400).

When the parent process closes or terminates abruptly, the Windows kernel guarantees
immediate, unconditional termination of the worker and all child processes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JobObjectExtendedLimitInformation = 9


class JobObject:
	"""Base protocol / interface for Win32 Job Object wrapper."""

	def assign_process(self, process_or_handle: int | Any) -> None:
		"""Assign a process handle or subprocess.Popen instance to this job object."""
		raise NotImplementedError

	def close(self) -> None:
		"""Close the job object handle."""
		raise NotImplementedError

	@property
	def is_valid(self) -> bool:
		"""Return True if the underlying handle is open and valid."""
		raise NotImplementedError

	def __enter__(self) -> JobObject:
		return self

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
		self.close()


class PyWin32JobObject(JobObject):
	"""Job Object implementation utilizing pywin32 (win32job, win32api)."""

	def __init__(self) -> None:
		import win32api
		import win32job

		self._win32job = win32job
		self._win32api = win32api
		self._handle: Any = self._win32job.CreateJobObject(None, "")
		if not self._handle:
			raise OSError("Failed to create Win32 Job Object via pywin32")

		info = self._win32job.QueryInformationJobObject(
			self._handle,
			self._win32job.JobObjectExtendedLimitInformation,
		)
		flags = (
			JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			| JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
		)
		info["BasicLimitInformation"]["LimitFlags"] |= flags
		self._win32job.SetInformationJobObject(
			self._handle,
			self._win32job.JobObjectExtendedLimitInformation,
			info,
		)
		logger.debug(
			"PyWin32JobObject configured with KILL_ON_JOB_CLOSE (0x%04X)", flags
		)

	def assign_process(self, process_or_handle: int | Any) -> None:
		if not self.is_valid:
			raise OSError("Cannot assign process to a closed JobObject")

		handle_val: int
		if isinstance(process_or_handle, subprocess.Popen):
			handle_val = int(process_or_handle._handle)
		elif hasattr(process_or_handle, "handle"):
			handle_val = int(process_or_handle.handle)
		elif hasattr(process_or_handle, "__int__"):
			handle_val = int(process_or_handle)
		else:
			handle_val = int(process_or_handle)

		self._win32job.AssignProcessToJobObject(self._handle, handle_val)
		logger.debug(
			"PyWin32JobObject assigned process handle %s successfully", handle_val
		)

	def close(self) -> None:
		if self._handle is not None:
			try:
				self._win32api.CloseHandle(self._handle)
			except Exception as exc:
				logger.warning("Error closing PyWin32JobObject handle: %s", exc)
			finally:
				self._handle = None

	@property
	def is_valid(self) -> bool:
		return self._handle is not None


class IO_COUNTERS(ctypes.Structure):
	_fields_ = [
		("ReadOperationCount", ctypes.c_uint64),
		("WriteOperationCount", ctypes.c_uint64),
		("OtherOperationCount", ctypes.c_uint64),
		("ReadTransferCount", ctypes.c_uint64),
		("WriteTransferCount", ctypes.c_uint64),
		("OtherTransferCount", ctypes.c_uint64),
	]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
	_fields_ = [
		("PerProcessUserTimeLimit", ctypes.c_int64),
		("PerJobUserTimeLimit", ctypes.c_int64),
		("LimitFlags", wintypes.DWORD),
		("MinimumWorkingSetSize", ctypes.c_size_t),
		("MaximumWorkingSetSize", ctypes.c_size_t),
		("ActiveProcessLimit", wintypes.DWORD),
		("Affinity", ctypes.c_size_t),
		("PriorityClass", wintypes.DWORD),
		("SchedulingClass", wintypes.DWORD),
	]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
	_fields_ = [
		("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
		("IoInfo", IO_COUNTERS),
		("ProcessMemoryLimit", ctypes.c_size_t),
		("JobMemoryLimit", ctypes.c_size_t),
		("PeakProcessMemoryLimit", ctypes.c_size_t),
		("PeakJobMemoryLimit", ctypes.c_size_t),
	]


class CtypesJobObject(JobObject):
	"""Job Object fallback implementation utilizing pure ctypes WinDLL."""

	def __init__(self) -> None:
		self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
		self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
		self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
		self._kernel32.SetInformationJobObject.argtypes = [
			ctypes.c_void_p,
			ctypes.c_int,
			ctypes.c_void_p,
			wintypes.DWORD,
		]
		self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
		self._kernel32.AssignProcessToJobObject.argtypes = [
			ctypes.c_void_p,
			ctypes.c_void_p,
		]
		self._kernel32.CloseHandle.restype = wintypes.BOOL
		self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

		self._handle = self._kernel32.CreateJobObjectW(None, None)
		if not self._handle:
			err = ctypes.get_last_error()
			raise OSError(f"CreateJobObjectW failed with Win32 error code {err}")

		info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
		flags = (
			JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			| JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
		)
		info.BasicLimitInformation.LimitFlags = flags

		ok = self._kernel32.SetInformationJobObject(
			self._handle,
			JobObjectExtendedLimitInformation,
			ctypes.byref(info),
			ctypes.sizeof(info),
		)
		if not ok:
			err = ctypes.get_last_error()
			self._kernel32.CloseHandle(self._handle)
			self._handle = None
			raise OSError(f"SetInformationJobObject failed with Win32 error code {err}")

		logger.debug(
			"CtypesJobObject configured with KILL_ON_JOB_CLOSE (0x%04X)", flags
		)

	def assign_process(self, process_or_handle: int | Any) -> None:
		if not self.is_valid:
			raise OSError("Cannot assign process to a closed JobObject")

		handle_val: int
		if isinstance(process_or_handle, subprocess.Popen):
			handle_val = int(process_or_handle._handle)
		elif hasattr(process_or_handle, "handle"):
			handle_val = int(process_or_handle.handle)
		elif hasattr(process_or_handle, "__int__"):
			handle_val = int(process_or_handle)
		else:
			handle_val = int(process_or_handle)

		ok = self._kernel32.AssignProcessToJobObject(
			ctypes.c_void_p(self._handle),
			ctypes.c_void_p(handle_val),
		)
		if not ok:
			err = ctypes.get_last_error()
			raise OSError(
				f"AssignProcessToJobObject failed with Win32 error code {err}"
			)
		logger.debug(
			"CtypesJobObject assigned process handle %s successfully", handle_val
		)

	def close(self) -> None:
		if self._handle is not None:
			try:
				self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
			except Exception as exc:
				logger.warning("Error closing CtypesJobObject handle: %s", exc)
			finally:
				self._handle = None

	@property
	def is_valid(self) -> bool:
		return self._handle is not None


class DummyJobObject(JobObject):
	"""No-op Job Object implementation for non-Windows platforms."""

	def __init__(self) -> None:
		self._valid = True
		logger.debug("DummyJobObject initialized (non-Windows platform)")

	def assign_process(self, process_or_handle: int | Any) -> None:
		pass

	def close(self) -> None:
		self._valid = False

	@property
	def is_valid(self) -> bool:
		return self._valid


def is_job_object_supported() -> bool:
	"""Check if Win32 Job Objects are supported on this operating system."""
	return sys.platform == "win32" or os.name == "nt"


def create_worker_job_object() -> JobObject:
	"""Create and configure a Win32 Job Object with KILL_ON_JOB_CLOSE.

	Tries pywin32 first, falling back to pure ctypes if pywin32 is not installed.
	On non-Windows platforms, returns a dummy no-op JobObject.
	"""
	if not is_job_object_supported():
		return DummyJobObject()

	try:
		return PyWin32JobObject()
	except Exception as pywin32_err:
		logger.debug(
			"pywin32 JobObject initialization failed (%s); trying ctypes fallback",
			pywin32_err,
		)
		try:
			return CtypesJobObject()
		except Exception as ctypes_err:
			logger.error("ctypes JobObject fallback also failed: %s", ctypes_err)
			raise OSError(
				f"Failed to create Windows Job Object: pywin32 failed ({pywin32_err}), "
				f"ctypes failed ({ctypes_err})"
			) from ctypes_err


def assign_process_to_job(job_obj: JobObject, process_handle: int | Any) -> None:
	"""Assign a process handle or subprocess.Popen instance to a JobObject."""
	job_obj.assign_process(process_handle)
