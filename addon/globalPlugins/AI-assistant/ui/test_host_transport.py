# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

PACKAGE_NAME = "ui_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


def _load_module(module_name: str, file_name: str):
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


host_transport = _load_module("host_transport", "host_transport.py")
HostPipeTransport = host_transport.HostPipeTransport


class HostPipeTransportTests(unittest.TestCase):
	def test_close_sets_stop_event(self) -> None:
		transport = HostPipeTransport(r"\\.\pipe\cmd", event_pipe_name=r"\\.\pipe\evt")

		transport.close()

		self.assertTrue(transport._stop_event.is_set())


if __name__ == "__main__":
	unittest.main()
