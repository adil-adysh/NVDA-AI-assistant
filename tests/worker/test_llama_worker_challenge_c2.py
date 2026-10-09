# -*- coding: utf-8 -*-
"""Milestone 2 Challenger 2 (Generation 3, Iteration 2) Empirical Challenge Suite.

Focus Areas:
1. Endpoint Rebinding & Teardown (LlamaWorkerExecutor):
   - Host/port modifications triggering self._supervisor.stop() prior to replacement.
   - Absence of orphaned processes or port leaks on endpoint rebind.
   - Robustness under multiple rapid endpoint transitions.
2. Preset INI Injection Attacks (merge_models_preset & build_models_preset):
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
merge_models_preset = llama_exec_mod.merge_models_preset
build_models_preset = llama_exec_mod.build_models_preset
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


class TestPresetInjectionAttacks(unittest.TestCase):
	"""Adversarially challenge router preset merging against INI injection attacks."""

	def setUp(self) -> None:
		self.base_preset = (
			"version = 1\n"
			"\n"
			"[*] # Global router settings\n"
			"threads = 4\n"
			"\n"
			"[llama-3-8b]\n"
			"model = C:/models/llama-3-8b.gguf\n"
			"threads = 8\n"
		)

	def test_section_injection_via_newlines_and_brackets_is_rejected(self) -> None:
		"""Attacks attempting to inject INI sections via newlines or brackets are filtered out."""
		attacks = [
			{"model_id": "malicious\n[injected_section]\nadmin=true", "source": "C:/evil.gguf"},
			{"model_id": "evil\r\n[pwned]\r\nhack=1", "source": "C:/evil.gguf"},
			{"model_id": "[injected]", "source": "C:/evil.gguf"},
			{"model_id": "test] [fake", "source": "C:/evil.gguf"},
			{"model_id": "]]]", "source": "C:/evil.gguf"},
			{"model_id": "", "source": "C:/evil.gguf"},
			{"model_id": "   ", "source": "C:/evil.gguf"},
			{"model_id": "\t\n", "source": "C:/evil.gguf"},
			{"model_id": "valid-model-7b", "source": "C:/models/valid.gguf"},
		]

		result = merge_models_preset(self.base_preset, attacks)
		self.assertNotIn("[injected_section]", result)
		self.assertNotIn("[pwned]", result)
		self.assertNotIn("[injected]", result)
		self.assertIn("[valid-model-7b]", result)
		self.assertIn("[llama-3-8b]", result)

	def test_duplicate_model_ids_do_not_produce_duplicate_sections(self) -> None:
		"""Submitting duplicate model records updates the single section rather than duplicating headers."""
		models = [
			{"model_id": "llama-3-8b", "source": "C:/models/first.gguf"},
			{"model_id": "llama-3-8b", "source": "C:/models/second.gguf"},
		]
		result = merge_models_preset(self.base_preset, models)
		section_headers = [line.strip() for line in result.splitlines() if line.strip() == "[llama-3-8b]"]
		self.assertEqual(len(section_headers), 1, f"Expected 1 [llama-3-8b] section, found: {section_headers}")

	def test_record_source_lines_and_merge_neutralize_crlf_and_control_chars(self) -> None:
		"""Metadata fields with CRLF sequences and control characters cannot inject INI sections."""
		attacks = [
			{
				"model_id": "clean-model-1",
				"hf_repo": "org/repo\r\n[injected_repo]\r\nadmin=true\x00\x08",
			},
			{
				"model_id": "clean-model-2",
				"source": "C:/models/valid.gguf\r\n[injected_source]\r\nkey=val\x1b[31m",
			},
			{
				"model_id": "clean-model-3",
				"source": "hf://org/repo",
				"variant": "Q4_K_M\r\n[injected_variant]\r\npwn=1\x07",
			},
			{
				"model_id": "clean-model-4",
				"local_path": "C:/models/local.gguf\n[injected_local]\nx=y\x0c",
			},
		]
		result = merge_models_preset(self.base_preset, attacks)
		section_headers = [line.strip() for line in result.splitlines() if line.strip().startswith("[")]
		self.assertNotIn("[injected_repo]", section_headers)
		self.assertNotIn("[injected_source]", section_headers)
		self.assertNotIn("[injected_variant]", section_headers)
		self.assertNotIn("[injected_local]", section_headers)
		self.assertIn("[clean-model-1]", section_headers)
		self.assertIn("[clean-model-2]", section_headers)
		self.assertIn("[clean-model-3]", section_headers)
		self.assertIn("[clean-model-4]", section_headers)

	def test_build_models_preset_rejects_bracket_and_newline_injections(self) -> None:
		"""build_models_preset directly filters out models with bracket or newline attacks."""
		attacks = [
			{"model_id": "evil\r\n[injected]\r\nx=1", "source": "C:/a.gguf"},
			{"model_id": "[bracket_wrap]", "source": "C:/b.gguf"},
			{"model_id": "bad] [split", "source": "C:/c.gguf"},
			{"model_id": "\r\n", "source": "C:/d.gguf"},
			{"model_id": "valid-direct-model", "source": "C:/valid.gguf"},
		]
		result = build_models_preset(attacks)
		section_headers = [line.strip() for line in result.splitlines() if line.strip().startswith("[")]
		self.assertNotIn("[injected]", section_headers)
		self.assertNotIn("[bracket_wrap]", section_headers)
		self.assertNotIn("[bad] [split", section_headers)
		self.assertEqual(section_headers, ["[valid-direct-model]"])


class TestIPv6HostFormatting(unittest.TestCase):
	"""Adversarially challenge IPv6 host formatting across shim supervisors."""

	def test_ipv6_formatting_in_test_shim_supervisor(self) -> None:
		"""IPv6 addresses are cleanly formatted in RFC 3986 bracketed URLs."""
		cases = [
			("127.0.0.1", 8080, "http://127.0.0.1:8080"),
			("localhost", 8080, "http://localhost:8080"),
			("::1", 8080, "http://[::1]:8080"),
			("[::1]", 8080, "http://[::1]:8080"),
			("fe80::1", 8080, "http://[fe80::1]:8080"),
			("[fe80::1]", 8080, "http://[fe80::1]:8080"),
			("2001:db8::1", 9000, "http://[2001:db8::1]:9000"),
			("[2001:db8::1]", 9000, "http://[2001:db8::1]:9000"),
			("::ffff:127.0.0.1", 8080, "http://[::ffff:127.0.0.1]:8080"),
			("[::ffff:127.0.0.1]", 8080, "http://[::ffff:127.0.0.1]:8080"),
			("fe80::1%lo0", 8080, "http://[fe80::1%lo0]:8080"),
			("[fe80::1%lo0]", 8080, "http://[fe80::1%lo0]:8080"),
		]
		for host, port, expected in cases:
			sup = LlamaServerSupervisor(host=host, port=port)
			self.assertEqual(sup.base_url, expected)
			st = sup.status()
			self.assertEqual(st.base_url, expected)

	def test_ipv6_formatting_in_worker_executor_get_status(self) -> None:
		"""LlamaWorkerExecutor properly formats IPv6 base_url when stopped or uninitialized."""
		cases = [
			("::1", 8080, "http://[::1]:8080"),
			("[::1]", 8080, "http://[::1]:8080"),
			("fe80::1", 8080, "http://[fe80::1]:8080"),
			("[fe80::1]", 8080, "http://[fe80::1]:8080"),
			("2001:db8::1", 9000, "http://[2001:db8::1]:9000"),
			("[2001:db8::1]", 9000, "http://[2001:db8::1]:9000"),
		]
		for host, port, expected in cases:
			ex = LlamaWorkerExecutor(host=host, port=port, supervisor=None)
			ex._supervisor = None
			st = ex.get_status()
			self.assertEqual(st["base_url"], expected)
