"""Application-facing diagnostics port; implementations own all IO and settings."""
from typing import Protocol


class RequestDiagnosticRecord(Protocol):
	def to_log_record(self) -> dict[str, object]: ...


class RequestDiagnostics(Protocol):
	def is_enabled(self) -> bool: ...
	def report(self, metrics: RequestDiagnosticRecord) -> None: ...


class NullRequestDiagnostics:
	def is_enabled(self) -> bool:
		return False

	def report(self, metrics: RequestDiagnosticRecord) -> None:
		pass


class TaskDiagnostics(Protocol):
	def emit(self, event: str, operation_id: str, **attributes: object) -> None: ...


class NullTaskDiagnostics:
	def emit(self, event: str, operation_id: str, **attributes: object) -> None:
		pass
