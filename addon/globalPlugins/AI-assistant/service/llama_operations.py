"""Application-owned model lifecycle operations; observers never own cancellation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import logging
import re
import threading
import time
import uuid

from ..core.cancellation import cancellation_event_scope, RequestCancelled
from ..core.translation import _

log = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}


def safe_diagnostic(error):
	text = str(error)
	text = re.sub(r"(?i)(token|api[_-]?key|authorization|password)(\s*[:=]\s*)[^\s,;]+", r"\1\2[redacted]", text)
	text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", text)
	return text[:2000]


@dataclass(frozen=True)
class ModelOperation:
	operation_id: str
	model_id: str
	kind: str
	state: str
	message: str
	error: str = ""
	history: tuple[str, ...] = ()
	updated_at: float = 0


class ModelOperations:
	def __init__(self):
		self._lock = threading.RLock()
		self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="AIModelOperation")
		self._records, self._events, self._futures = {}, {}, {}
		self._observers, self._handlers = set(), {}
		self._closed = False

	def bind(self, *, load, unload):
		with self._lock:
			self._handlers = {"load": load, "unload": unload}

	def snapshots(self):
		with self._lock:
			return tuple(self._records.values())

	def active(self, model_id=None):
		return tuple(item for item in self.snapshots() if item.state in ACTIVE and (model_id is None or item.model_id == model_id))

	def subscribe(self, callback):
		with self._lock:
			self._observers.add(callback)
		def detach():
			with self._lock:
				self._observers.discard(callback)
		return detach

	def _publish(self, identifier, **changes):
		with self._lock:
			previous = self._records[identifier]
			message = safe_diagnostic(changes.get("message", previous.message))
			history = previous.history
			if not history or history[-1] != message:
				history = (*history[-31:], message)
			item = replace(previous, **{**changes, "message": message, "history": history, "updated_at": time.time()})
			self._records[identifier] = item
			observers = tuple(self._observers)
		for callback in observers:
			try:
				callback(item)
			except Exception:
				log.debug("Model operation observer failed", exc_info=True)

	def start(self, model_id, kind):
		with self._lock:
			if self._closed:
				raise RuntimeError(_("Model operations are shutting down."))
			if kind not in self._handlers:
				raise ValueError(_("Unsupported model operation."))
			for item in self.active(model_id):
				if item.kind == kind:
					return item
				raise ValueError(_("An operation is already running for this configuration. Stop it or wait for completion."))
			# Bound retained terminal history; active operations are never discarded.
			for identifier in tuple(self._records):
				if len(self._records) < 64:
					break
				if self._records[identifier].state not in ACTIVE:
					self._records.pop(identifier)
					self._events.pop(identifier, None)
					self._futures.pop(identifier, None)
			identifier = uuid.uuid4().hex
			item = ModelOperation(identifier, model_id, kind, "queued", _("Queued"), updated_at=time.time())
			self._records[identifier] = item
			event = self._events[identifier] = threading.Event()
			handler = self._handlers[kind]
			self._futures[identifier] = self._executor.submit(self._run, item, event, handler)
			return item

	def _run(self, item, cancel, handler):
		try:
			with cancellation_event_scope(cancel):
				self._publish(item.operation_id, state="running", message=_("Loading model...") if item.kind == "load" else _("Unloading model..."))
				handler(item.model_id, lambda message: self._publish(item.operation_id, message=message), cancel)
			if cancel.is_set():
				self._publish(item.operation_id, state="stopped", message=_("Operation stopped. Configuration and files were kept."))
			else:
				self._publish(item.operation_id, state="succeeded", message=_("Model loaded.") if item.kind == "load" else _("Model unloaded."))
		except Exception as error:
			stopped = cancel.is_set() or isinstance(error, RequestCancelled)
			message = _("Operation stopped. Configuration and files were kept.") if stopped else safe_diagnostic(error)
			self._publish(item.operation_id, state="stopped" if stopped else "failed", message=message, error="" if stopped else message)

	def cancel(self, operation_id):
		with self._lock:
			if operation_id in self._events and self._records[operation_id].state in ACTIVE:
				self._events[operation_id].set()

	def wait(self, operation_id, timeout=None):
		with self._lock:
			future = self._futures.get(operation_id)
		if future is not None:
			future.result(timeout=timeout)

	def shutdown(self):
		with self._lock:
			self._closed = True
			for identifier, event in self._events.items():
				if self._records[identifier].state in ACTIVE:
					event.set()
		self._executor.shutdown(wait=False, cancel_futures=False)


_registries = {}
_registry_lock = threading.Lock()
_shutting_down = False


def get_model_operations(key, *, load, unload):
	with _registry_lock:
		if _shutting_down:
			raise RuntimeError(_("Model operations are shutting down."))
		registry = _registries.get(key)
		if registry is None or registry._closed:
			registry = _registries[key] = ModelOperations()
		registry.bind(load=load, unload=unload)
		return registry


def shutdown_model_operations():
	global _shutting_down
	with _registry_lock:
		_shutting_down = True
		registries = tuple(_registries.values())
		_registries.clear()
	for registry in registries:
		registry.shutdown()


def initialize_model_operations():
	global _shutting_down
	with _registry_lock:
		_shutting_down = False
