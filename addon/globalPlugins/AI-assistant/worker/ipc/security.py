# -*- coding: utf-8 -*-
"""Win32 Security DACL builder for Named Pipes.

Enforces Invariant A18 and addresses FW-05:
Creates a Windows Security Descriptor with an explicit Discretionary Access Control
List (DACL) that permits GENERIC_READ | GENERIC_WRITE | SYNCHRONIZE strictly to:
1. The Current User SID (TOKEN_USER of the running user session).
2. The Built-in Administrators SID (S-1-5-32-544).

All other local interactive accounts, guest accounts, and network accounts are denied.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Standard Win32 access rights
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
SYNCHRONIZE = 0x00100000
TOKEN_QUERY = 0x0008
TokenUser = 1
WinBuiltinAdministratorsSid = 26
ACL_REVISION = 2


def get_current_user_sid_str() -> str:
	"""Retrieve the String SID of the current user account."""
	if sys.platform != "win32" and os.name != "nt":
		return "S-1-5-21-0-0-0-1000"

	# Try pywin32 first
	try:
		import win32process
		import win32security

		token = win32security.OpenProcessToken(
			win32process.GetCurrentProcess(),
			win32security.TOKEN_QUERY,
		)
		user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
		return str(win32security.ConvertSidToStringSid(user_sid))
	except Exception:
		pass

	# ctypes fallback
	advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	kernel32.GetCurrentProcess.restype = ctypes.c_void_p
	advapi32.OpenProcessToken.argtypes = [
		ctypes.c_void_p,
		wintypes.DWORD,
		ctypes.POINTER(wintypes.HANDLE),
	]
	advapi32.ConvertSidToStringSidW.argtypes = [
		ctypes.c_void_p,
		ctypes.POINTER(wintypes.LPWSTR),
	]
	advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

	h_tok = wintypes.HANDLE()
	ok = advapi32.OpenProcessToken(
		kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_tok)
	)
	if not ok:
		err = ctypes.get_last_error()
		raise OSError(f"OpenProcessToken failed with Win32 error {err}")

	try:
		buf_len = wintypes.DWORD(0)
		advapi32.GetTokenInformation(h_tok, TokenUser, None, 0, ctypes.byref(buf_len))
		buf = (ctypes.c_byte * buf_len.value)()
		ok = advapi32.GetTokenInformation(
			h_tok, TokenUser, ctypes.byref(buf), buf_len.value, ctypes.byref(buf_len)
		)
		if not ok:
			err = ctypes.get_last_error()
			raise OSError(f"GetTokenInformation failed with Win32 error {err}")

		p_sid = ctypes.c_void_p.from_buffer(buf).value
		p_str = wintypes.LPWSTR()
		ok = advapi32.ConvertSidToStringSidW(p_sid, ctypes.byref(p_str))
		if not ok or not p_str.value:
			err = ctypes.get_last_error()
			raise OSError(f"ConvertSidToStringSidW failed with Win32 error {err}")

		sid_str = p_str.value
		kernel32.LocalFree(p_str)
		return sid_str
	finally:
		kernel32.CloseHandle(h_tok)


def _build_security_attributes_pywin32() -> Any:
	"""Construct SECURITY_ATTRIBUTES via pywin32."""
	import ntsecuritycon
	import win32process
	import win32security

	token = win32security.OpenProcessToken(
		win32process.GetCurrentProcess(),
		win32security.TOKEN_QUERY,
	)
	user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
	admin_sid = win32security.CreateWellKnownSid(
		win32security.WinBuiltinAdministratorsSid
	)

	dacl = win32security.ACL()
	access_mask = (
		ntsecuritycon.GENERIC_READ
		| ntsecuritycon.GENERIC_WRITE
		| ntsecuritycon.SYNCHRONIZE
	)
	dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access_mask, user_sid)
	dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access_mask, admin_sid)

	sd = win32security.SECURITY_DESCRIPTOR()
	sd.SetSecurityDescriptorDacl(True, dacl, False)
	sd.SetSecurityDescriptorOwner(user_sid, False)
	sd.SetSecurityDescriptorGroup(admin_sid, False)

	sa = win32security.SECURITY_ATTRIBUTES()
	sa.SECURITY_DESCRIPTOR = sd
	sa.bInheritHandle = False
	return sa


class SECURITY_ATTRIBUTES_CTYPES(ctypes.Structure):
	_fields_ = [
		("nLength", wintypes.DWORD),
		("lpSecurityDescriptor", ctypes.c_void_p),
		("bInheritHandle", wintypes.BOOL),
	]


class CtypesSecurityAttributesHolder:
	"""Wraps ctypes SECURITY_ATTRIBUTES and owns the allocated Security Descriptor."""

	def __init__(self, sd_handle: int, sa: SECURITY_ATTRIBUTES_CTYPES) -> None:
		self._sd_handle = sd_handle
		self.sa = sa

	def close(self) -> None:
		if self._sd_handle:
			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
			kernel32.LocalFree(ctypes.c_void_p(self._sd_handle))
			self._sd_handle = 0

	def __del__(self) -> None:
		self.close()


def _build_security_attributes_ctypes() -> CtypesSecurityAttributesHolder:
	"""Construct SECURITY_ATTRIBUTES via SDDL and ctypes."""
	advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
	advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
		wintypes.LPCWSTR,
		wintypes.DWORD,
		ctypes.POINTER(ctypes.c_void_p),
		ctypes.POINTER(wintypes.DWORD),
	]
	advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
		wintypes.BOOL
	)

	user_sid = get_current_user_sid_str()
	# SDDL: Discretionary ACL granting Generic Read + Write (GRGW) to User and Administrators (BA)
	sddl = f"D:(A;;GRGW;;;{user_sid})(A;;GRGW;;;BA)"

	p_sd = ctypes.c_void_p()
	sd_size = wintypes.DWORD(0)
	ok = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
		sddl, 1, ctypes.byref(p_sd), ctypes.byref(sd_size)
	)
	if not ok or not p_sd.value:
		err = ctypes.get_last_error()
		raise OSError(
			f"ConvertStringSecurityDescriptorToSecurityDescriptorW failed with Win32 error {err}"
		)

	sa = SECURITY_ATTRIBUTES_CTYPES()
	sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES_CTYPES)
	sa.lpSecurityDescriptor = p_sd.value
	sa.bInheritHandle = False
	return CtypesSecurityAttributesHolder(p_sd.value, sa)


def build_user_only_security_attributes() -> Any:
	"""Build SECURITY_ATTRIBUTES restricting named pipe access strictly to current user and Admins.

	Returns pywin32 SECURITY_ATTRIBUTES if available, else CtypesSecurityAttributesHolder.
	On non-Windows platforms, returns None.
	"""
	if sys.platform != "win32" and os.name != "nt":
		return None

	try:
		return _build_security_attributes_pywin32()
	except Exception as exc:
		logger.debug(
			"pywin32 security attributes creation failed (%s); using ctypes SDDL fallback",
			exc,
		)
		return _build_security_attributes_ctypes()
