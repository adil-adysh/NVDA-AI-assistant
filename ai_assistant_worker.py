# -*- coding: utf-8 -*-
"""Authoritative Entrypoint for Out-of-Process AI Assistant Worker.

Runs out-of-process, enclosed in a Windows Job Object.
Accepts commands via Named Pipe and streams events asynchronously.
Enforces Invariants A16, A17, A18.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

# Configure sys.path so worker and core packages can be imported
_REPO_ROOT = Path(__file__).resolve().parent
_ADDON_ROOT = _REPO_ROOT / "addon" / "globalPlugins" / "AI-assistant"
if str(_ADDON_ROOT) not in sys.path:
	sys.path.insert(0, str(_ADDON_ROOT))
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from worker.server import WorkerServer  # noqa: E402


def setup_worker_logging(log_file: str | None, log_level: str) -> None:
	"""Configure worker process logging handlers."""
	level = getattr(logging, log_level.upper(), logging.INFO)
	handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
	if log_file:
		handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

	logging.basicConfig(
		level=level,
		format="%(asctime)s [%(levelname)s] (worker:%(process)d) %(name)s: %(message)s",
		handlers=handlers,
	)


def main() -> int:
	"""Parse CLI arguments and run WorkerServer."""
	parser = argparse.ArgumentParser(
		description="NVDA AI Assistant Background Worker"
	)
	parser.add_argument("--cmd-pipe", default=r"\\.\pipe\nvda_ai_worker_cmd")
	parser.add_argument("--evt-pipe", default=r"\\.\pipe\nvda_ai_worker_evt")
	parser.add_argument("--parent-pid", type=int, default=0)
	parser.add_argument("--log-file", default=None)
	parser.add_argument("--log-level", default="INFO")
	parser.add_argument("--instance-id", default=None)
	args = parser.parse_args()

	# Scope pipe names if instance-id is provided (for test concurrency)
	cmd_pipe = (
		f"{args.cmd_pipe}_{args.instance_id}"
		if args.instance_id
		else args.cmd_pipe
	)
	evt_pipe = (
		f"{args.evt_pipe}_{args.instance_id}"
		if args.instance_id
		else args.evt_pipe
	)

	setup_worker_logging(args.log_file, args.log_level)
	logger = logging.getLogger("worker.main")
	logger.info(
		"Starting AI Assistant Worker (PID=%d, Parent PID=%d, cmd=%s, evt=%s)",
		os.getpid(),
		args.parent_pid,
		cmd_pipe,
		evt_pipe,
	)

	server = WorkerServer(
		cmd_pipe_name=cmd_pipe,
		evt_pipe_name=evt_pipe,
		parent_pid=args.parent_pid,
	)

	try:
		server.serve_forever()
	except KeyboardInterrupt:
		logger.info("Worker received SIGINT; shutting down")
	except Exception as error:
		logger.exception("Worker server fatal error: %s", error)
		return 1
	finally:
		server.shutdown()

	logger.info("Worker process exited cleanly")
	return 0


if __name__ == "__main__":
	sys.exit(main())
