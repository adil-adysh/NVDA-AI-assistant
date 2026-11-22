from tests.support import load_addon_module


def test_cancellation_wins_over_normal_return_and_wrapped_failure():
	module = load_addon_module("core.operation_outcome", namespace="outcome_tests")
	assert module.resolve_outcome(cancelled=True) is module.OperationOutcome.CANCELLED
	assert module.resolve_outcome(cancelled=True, error=RuntimeError()) is module.OperationOutcome.CANCELLED
	assert module.resolve_outcome(cancelled=False, error=module.RequestCancelled()) is module.OperationOutcome.CANCELLED
	assert module.resolve_outcome(cancelled=False, error=RuntimeError()) is module.OperationOutcome.FAILED
	assert module.resolve_outcome(cancelled=False) is module.OperationOutcome.SUCCEEDED
