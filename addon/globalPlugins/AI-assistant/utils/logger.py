# -*- coding: utf-8 -*-
"""Standard logging facade and NVDA logHandler bridge.

Pure Python packages use standard library logging:
    import logging
    log = logging.getLogger(__name__)

When running inside NVDA, `attach_nvda_log_bridge()` connects standard
library logging to NVDA's authoritative `logHandler.log`, ensuring:
1. Records receive `record.name == "nvda"` so NVDA does not drop DEBUG/INFO logs.
2. Caller `codepath` is preserved in NVDA log entries.
3. Recursion and duplicate messages are strictly prevented.
4. When running outside NVDA (pure pytest, worker), this module is a clean no-op.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
	"""Return a standard library logger for the given module name."""
	return logging.getLogger(name)


class NVDALogBridge(logging.Handler):
	"""Logging handler that routes standard library LogRecords to NVDA's logHandler."""

	def emit(self, record: logging.LogRecord) -> None:
		# Guard against infinite recursion: ignore records originating from NVDA or already bridged
		if record.name == "nvda" or getattr(record, "_nvda_bridged", False):
			return

		try:
			from logHandler import log as nvda_log

			# Mark original record so downstream handlers/filters know it was bridged
			record._nvda_bridged = True

			# Extract formatted message
			msg = record.getMessage()

			# Preserve true caller code path: e.g. "config.state._notify_provider_state_changed"
			if record.funcName and record.funcName != "<module>":
				codepath = f"{record.name}.{record.funcName}"
			else:
				codepath = record.name

			# Dispatch through NVDA logger so new record has name == 'nvda'
			nvda_log._log(
				record.levelno,
				msg,
				(),
				exc_info=record.exc_info,
				extra={"codepath": codepath},
				codepath=codepath,
				stack_info=record.stack_info,
			)
		except Exception:
			self.handleError(record)


def _drop_bridged_filter(record: logging.LogRecord) -> bool:
	"""Filter for NVDA's root handler to prevent duplicate entries for bridged records."""
	return not getattr(record, "_nvda_bridged", False)


def attach_nvda_log_bridge(logger_name: str | None = None) -> bool:
	"""Attach NVDALogBridge to the specified logger or root logger.

	Returns True if bridge was attached, False if outside NVDA or already attached.
	"""
	try:
		from logHandler import logHandler as nvda_handler
	except ImportError:
		return False  # Running in pure Python environment; no-op

	target_logger = logging.getLogger(logger_name)
	target_logger.setLevel(logging.DEBUG)

	# Avoid duplicate bridge attachment
	for handler in target_logger.handlers:
		if isinstance(handler, NVDALogBridge):
			return True

	bridge = NVDALogBridge()
	target_logger.addHandler(bridge)

	# Install duplication prevention filter on NVDA's root logHandler
	if nvda_handler is not None and hasattr(nvda_handler, "addFilter"):
		# Ensure we only add filter once
		filters = getattr(nvda_handler, "filters", [])
		if _drop_bridged_filter not in filters:
			nvda_handler.addFilter(_drop_bridged_filter)

	return True
