"""Request-local worker cancellation; never stored on shared runtime objects."""
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("worker_job_token", default=None)


def current_job_token():
	return _current.get()


def check_job_cancelled():
	token = _current.get()
	if token is not None:
		token.check_cancelled()


@contextmanager
def job_execution_scope(token):
	marker = _current.set(token)
	try:
		yield
	finally:
		_current.reset(marker)
