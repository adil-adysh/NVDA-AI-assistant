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


host_lifecycle = _load_module("host_lifecycle", "host_lifecycle.py")
HostLifecycleService = host_lifecycle.HostLifecycleService
HostLifecycleState = host_lifecycle.HostLifecycleState


class HostLifecycleTests(unittest.TestCase):
	def test_prepare_primary_action_resets_failed_state(self) -> None:
		service = HostLifecycleService()
		service.mark_failed()

		service.prepare_primary_action()

		self.assertEqual(service.state, HostLifecycleState.STOPPED)

	def test_ensure_started_transitions_to_starting_before_starter_runs(self) -> None:
		service = HostLifecycleService()
		observed_states: list[HostLifecycleState] = []

		def starter() -> None:
			observed_states.append(service.state)

		service.ensure_started(starter)

		self.assertEqual(observed_states, [HostLifecycleState.STARTING])
		self.assertEqual(service.state, HostLifecycleState.STARTING)

	def test_mark_host_closed_keeps_failed_state_intact(self) -> None:
		service = HostLifecycleService()
		service.mark_failed()

		service.mark_host_closed()

		self.assertEqual(service.state, HostLifecycleState.FAILED)

	def test_mark_host_closed_sets_hidden_when_healthy(self) -> None:
		service = HostLifecycleService()
		service.mark_ready()

		service.mark_host_closed()

		self.assertEqual(service.state, HostLifecycleState.HIDDEN)


if __name__ == "__main__":
	unittest.main()
