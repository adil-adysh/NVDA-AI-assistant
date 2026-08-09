# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from test_bootstrap import load_module

host_lifecycle = load_module("host_lifecycle", "host_lifecycle.py")
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
