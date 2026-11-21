# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import time
import uuid

import logging

from .metrics import RequestMetrics
from .events import DiagnosticEvent
from ..config.settings import get_request_metrics_log_path, get_request_metrics_logging_enabled

log = logging.getLogger(__name__)


class MetricsReporter:
	def is_enabled(self) -> bool:
		return True

	def report(self, metrics: RequestMetrics) -> None:
		raise NotImplementedError

	def report_event(self, event: DiagnosticEvent) -> None:
		"""Report a privacy-safe lifecycle event when supported."""
		return None


class FileMetricsReporter(MetricsReporter):
	MAX_LOG_BYTES = 5 * 1024 * 1024
	BACKUP_COUNT = 3
	_write_lock = threading.RLock()

	def report(self, metrics: RequestMetrics) -> None:
		self._write_record(metrics.to_log_record())

	def report_event(self, event: DiagnosticEvent) -> None:
		self._write_record(event.to_record())

	def is_enabled(self) -> bool:
		return get_request_metrics_logging_enabled()

	def _write_record(self, record: dict[str, object]) -> None:
		if not get_request_metrics_logging_enabled():
			return

		log_path = Path(get_request_metrics_log_path()).expanduser()
		try:
			log_path.parent.mkdir(parents=True, exist_ok=True)
		except Exception:
			log.exception("Unable to create metrics log folder %s", log_path.parent)
			return
		try:
			line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
			with self._write_lock:
				self._rotate_if_needed(log_path, len(line.encode("utf-8")))
				with log_path.open("a", encoding="utf-8", newline="\n") as handle:
					handle.write(line)
		except Exception:
			log.exception("Unable to write request metrics log to %s", log_path)

	@classmethod
	def _rotate_if_needed(cls, log_path: Path, next_record_bytes: int) -> None:
		try:
			current_size = log_path.stat().st_size
		except FileNotFoundError:
			return
		if current_size == 0 or current_size + next_record_bytes <= cls.MAX_LOG_BYTES:
			return
		generation = Path(f"{log_path}.{time.time_ns():020d}-{uuid.uuid4().hex[:8]}")
		# Commit the active generation under a unique name before pruning history.
		# If it is locked on Windows, no existing backup has been changed.
		log_path.replace(generation)
		try:
			backup_pattern = re.compile(rf"{re.escape(log_path.name)}\.(\d{{20}}-\w{{8}})")
			backups = sorted(
				(
					candidate
					for candidate in log_path.parent.iterdir()
					if candidate.is_file() and backup_pattern.fullmatch(candidate.name)
				),
				key=lambda candidate: backup_pattern.fullmatch(candidate.name).group(1),
			)
			while len(backups) > cls.BACKUP_COUNT:
				oldest = backups.pop(0)
				oldest.unlink()
		except Exception:
			if generation.exists() and not log_path.exists():
				try:
					generation.replace(log_path)
				except Exception:
					log.exception("Unable to restore diagnostics log after rotation failed")
			raise
