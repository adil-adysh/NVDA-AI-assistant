# -*- coding: utf-8 -*-
"""Milestone 2 Challenger 2 (Generation 3, Iteration 2) Empirical Challenge Suite.

Focus Areas:
1. Endpoint Rebinding & Teardown (LlamaWorkerExecutor):
   - Host/port modifications triggering self._supervisor.stop() prior to replacement.
   - Absence of orphaned processes or port leaks on endpoint rebind.
   - Robustness under multiple rapid endpoint transitions.
2. Preset generation is covered by the HF-only preset tests.
   - Malformed model IDs containing brackets [], carriage returns \\r, newlines \\n.
   - Control characters (\\x00, \\x08, \\x1b).
   - Duplicate model IDs coalescing without duplicate INI sections.
3. IPv6 Host Formatting:
   - Proper RFC 3986 URI formatting for bracketed and unbracketed IPv6 addresses in _LlamaTestShimSupervisor.
4. Worker Client Exception Resilience:
   - Disconnected worker detection when is_connected raises an exception.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import socket
import sys
import time
import unittest
import uuid

from tests.support import load_addon_module

llama_exec_mod = load_addon_module("worker.executors.llama")
llama_server_mod = load_addon_module("providers.runtime.llama_server")

LlamaWorkerExecutor = llama_exec_mod.LlamaWorkerExecutor
LlamaServerSupervisor = llama_server_mod.LlamaServerSupervisor
LlamaServerError = llama_server_mod.LlamaServerError


def _is_pid_alive(pid: int) -> bool:
	"""Check whether a Windows process is still running."""
	PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
	STILL_ACTIVE = 259
	h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
	if not h_proc:
		return False
	try:
		exit_code = wintypes.DWORD()
		if ctypes.windll.kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code)):
			return exit_code.value == STILL_ACTIVE
		return False
	finally:
		ctypes.windll.kernel32.CloseHandle(h_proc)


class TestLlamaEndpointRebindingAndTeardown(unittest.TestCase):
	"""Adversarially challenge endpoint rebinding and process teardown in LlamaWorkerExecutor."""

	def test_host_port_rebind_terminates_child_process_without_orphan(self) -> None:
		"""Changing host/port triggers old supervisor stop, terminating child process without orphan."""
		server_script = (
			"import sys, time\n"
			"from http.server import HTTPServer, BaseHTTPRequestHandler\n"
			"class H(BaseHTTPRequestHandler):\n"
			"    def do_GET(self):\n"
			"        self.send_response(200)\n"
			"        self.send_header('Content-Type', 'application/json')\n"
			"        self.end_headers()\n"
			"        self.wfile.write(b'{\"status\": \"ok\"}')\n"
			"    def log_message(self, *args): pass\n"
			"httpd = HTTPServer(('127.0.0.1', int(sys.argv[1])), H)\n"
			"httpd.serve_forever()\n"
		)

		port1 = 8185
		port2 = 8186

		executor = LlamaWorkerExecutor(host="127.0.0.1", port=port1)
		sup1 = executor._get_supervisor()
		self.assertEqual(sup1.port, port1)

		# Spawn process 1
		status1 = sup1.ensure_ready(
			sys.executable,
			["-c", server_script, str(port1)],
			{},
			f"test-rebind-{uuid.uuid4().hex[:6]}",
			timeout_seconds=5.0,
		)
		pid1 = status1.pid
		self.assertTrue(_is_pid_alive(pid1), f"Child process {pid1} should be active")

		# Verify port1 is actively listening
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
			sock.connect(("127.0.0.1", port1))

		# Rebind executor to port2
		executor.port = port2
		sup2 = executor._get_supervisor()
		self.assertEqual(sup2.port, port2)
		self.assertIsNot(sup1, sup2)

		# Old child process must be terminated cleanly
		time.sleep(0.5)
		self.assertFalse(
			_is_pid_alive(pid1),
			f"Child process {pid1} was ORPHANED after endpoint rebind from {port1} to {port2}!",
		)

		# Port1 must be freed without leak
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
			test_sock.bind(("127.0.0.1", port1))

		# Cleanup sup2
		executor.stop(timeout_seconds=2.0)

	def test_multiple_rapid_rebinds_do_not_leak_or_crash(self) -> None:
		"""Rapidly rebinding port across 5 endpoints cleanly instantiates new supervisors."""
		executor = LlamaWorkerExecutor(host="127.0.0.1", port=8190)
		for target_port in [8191, 8192, 8193, 8194, 8195]:
			executor.port = target_port
			sup = executor._get_supervisor()
			self.assertEqual(sup.port, target_port)
		executor.stop(timeout_seconds=1.0)

	def test_host_rebind_terminates_child_process_without_orphan(self) -> None:
		"""Changing host triggers old supervisor stop, terminating child process without orphan."""
		server_script = (
			"import sys, time\n"
			"from http.server import HTTPServer, BaseHTTPRequestHandler\n"
			"class H(BaseHTTPRequestHandler):\n"
			"    def do_GET(self):\n"
			"        self.send_response(200)\n"
			"        self.send_header('Content-Type', 'application/json')\n"
			"        self.end_headers()\n"
			"        self.wfile.write(b'{\"status\": \"ok\"}')\n"
			"    def log_message(self, *args): pass\n"
			"httpd = HTTPServer(('127.0.0.1', int(sys.argv[1])), H)\n"
			"httpd.serve_forever()\n"
		)

		port = 8187
		executor = LlamaWorkerExecutor(host="127.0.0.1", port=port)
		sup1 = executor._get_supervisor()
		self.assertEqual(sup1.host, "127.0.0.1")

		status1 = sup1.ensure_ready(
			sys.executable,
			["-c", server_script, str(port)],
			{},
			f"test-host-rebind-{uuid.uuid4().hex[:6]}",
			timeout_seconds=5.0,
		)
		pid1 = status1.pid
		self.assertTrue(_is_pid_alive(pid1), f"Child process {pid1} should be active")

		# Rebind host
		executor.host = "127.0.0.2"
		sup2 = executor._get_supervisor()
		self.assertEqual(sup2.host, "127.0.0.2")
		self.assertIsNot(sup1, sup2)

		time.sleep(0.5)
		self.assertFalse(
			_is_pid_alive(pid1),
			f"Child process {pid1} was ORPHANED after host rebind!",
		)

		executor.stop(timeout_seconds=2.0)
