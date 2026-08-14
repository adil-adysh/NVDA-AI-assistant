# -*- coding: utf-8 -*-
# Tests intentionally inspect transport internals (W0212) to drive
# lifecycle behavior.
# pylint: disable=protected-access
from __future__ import annotations

import unittest

from test_bootstrap import load_module

host_transport = load_module("host_transport", "host_transport.py")
HostPipeTransport = host_transport.HostPipeTransport


class HostPipeTransportTests(unittest.TestCase):
	def test_close_sets_stop_event(self) -> None:
		transport = HostPipeTransport(r"\\.\pipe\cmd", event_pipe_name=r"\\.\pipe\evt")

		transport.close()

		self.assertTrue(transport._stop_event.is_set())

	def test_read_line_uses_available_bytes_and_preserves_frame(self) -> None:
		class FakePipe:
			def PeekNamedPipe(self, _handle, _size):
				return b"", 4, 0

		class FakeFile:
			def ReadFile(self, _handle, size):
				if size != 4:
					raise AssertionError(f"expected read size 4, got {size}")
				return 0, b"ok\n"

		transport = HostPipeTransport(r"\\.\pipe\cmd")
		self.assertEqual(
			transport._read_line(None, FakeFile(), FakePipe(), timeout_seconds=1),
			b"ok",
		)

	def test_read_line_times_out_when_pipe_has_no_data(self) -> None:
		class FakePipe:
			def PeekNamedPipe(self, _handle, _size):
				return b"", 0, 0

		transport = HostPipeTransport(r"\\.\pipe\cmd")
		with self.assertRaises(TimeoutError):
			transport._read_line(None, object(), FakePipe(), timeout_seconds=0.01)


if __name__ == "__main__":
	unittest.main()
