# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from logHandler import log

from .metrics import RequestMetrics
from ..config.settings import get_request_metrics_log_path, get_request_metrics_logging_enabled


class MetricsReporter:
	def report(self, metrics: RequestMetrics) -> None:
		raise NotImplementedError


class FileMetricsReporter(MetricsReporter):
	def report(self, metrics: RequestMetrics) -> None:
		if not get_request_metrics_logging_enabled():
			return

		log_path = Path(get_request_metrics_log_path()).expanduser()
		try:
			log_path.parent.mkdir(parents=True, exist_ok=True)
		except Exception:
			log.exception("Unable to create metrics log folder %s", log_path.parent)
			return
		try:
			with log_path.open("a", encoding="utf-8") as handle:
				handle.write(json.dumps(metrics.to_log_record(), ensure_ascii=False))
				handle.write("\n")
		except Exception:
			log.exception("Unable to write request metrics log to %s", log_path)
