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


if __name__ == "__main__":
	unittest.main()
