"""Terminal operation rules shared by execution, presentation and diagnostics."""
from enum import Enum

from .cancellation import RequestCancelled


class OperationOutcome(str, Enum):
	SUCCEEDED = "succeeded"
	FAILED = "failed"
	CANCELLED = "cancelled"


def resolve_outcome(*, cancelled: bool, error: BaseException | None = None) -> OperationOutcome:
	if cancelled or isinstance(error, RequestCancelled):
		return OperationOutcome.CANCELLED
	return OperationOutcome.FAILED if error is not None else OperationOutcome.SUCCEEDED
