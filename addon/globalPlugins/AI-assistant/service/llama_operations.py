"""Application-owned model lifecycle operations; observers never own cancellation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
import logging
import re
import threading
import time
import uuid

from ..core.cancellation import cancellation_event_scope, check_cancelled
from ..core.translation import _
from ..core.operation_outcome import OperationOutcome, resolve_outcome

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
		self._lane = threading.RLock()
		self._local = threading.local()
		self._removing = False
		self._executing = set()

	def bind(self, *, load, unload, remove=None):
		with self._lock:
			self._handlers = {"load": load, "unload": unload}
			if remove is not None:
				self._handlers["remove"] = remove

	def _reserve_removal(self):
		if self._removing:
			raise ValueError(_("A preset removal is already running."))
		self._removing = True
		for event in (*self._executing, *self._events.values()):
			event.set()

	@contextmanager
	def execution(self, kind, cancel=None, *, reserved=False):
		"""Serialize endpoint mutations without holding admission or IPC locks."""
		if getattr(self._local, "depth", 0):
			check_cancelled()
			yield
			return
		cancel = cancel if cancel is not None else threading.Event()
		with self._lock:
			if self._closed:
				raise RuntimeError(_("Model operations are shutting down."))
			if kind == "remove":
				if not reserved:
					self._reserve_removal()
			elif self._removing:
				raise ValueError(_("A preset removal is running. Wait for completion."))
			if kind == "mutation" and self._executing:
				raise ValueError(_("A model operation is running. Wait for completion."))
			self._executing.add(cancel)
		try:
			with self._lane, cancellation_event_scope(cancel):
				check_cancelled()
				self._local.depth = 1
				try:
					yield
				finally:
					self._local.depth = 0
		finally:
			with self._lock:
				self._executing.discard(cancel)
				if kind == "remove":
					self._removing = False

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
			if self._removing:
				for item in self.active():
					if item.kind == kind == "remove" and item.model_id == model_id:
						return item
				raise ValueError(_("A preset removal is running. Wait for completion."))
			for item in self.active(model_id):
				if item.kind == kind:
					return item
				if kind == "remove":
					continue
				raise ValueError(_("An operation is already running for this configuration. Stop it or wait for completion."))
			# Bound retained terminal history; active operations are never discarded.
			for identifier in tuple(self._records):
				if len(self._records) < 64:
					break
				if self._records[identifier].state not in ACTIVE:
					self._records.pop(identifier)
					self._events.pop(identifier, None)
					self._futures.pop(identifier, None)
			if kind == "remove":
				self._reserve_removal()
			identifier = uuid.uuid4().hex
			item = ModelOperation(identifier, model_id, kind, "queued", _("Queued"), updated_at=time.time())
			self._records[identifier] = item
			event = self._events[identifier] = threading.Event()
			handler = self._handlers[kind]
			self._futures[identifier] = self._executor.submit(self._run, item, event, handler)
			return item

	def _run(self, item, cancel, handler):
		error = None
		try:
			with self.execution(item.kind, cancel, reserved=item.kind == "remove"):
				self._publish(item.operation_id, state="running", message={
					"load": _("Loading model..."), "unload": _("Unloading model..."),
					"remove": _("Removing preset..."),
				}[item.kind])
				handler(item.model_id, lambda message: self._publish(item.operation_id, message=message), cancel)
		except Exception as exc:
			error = exc
		outcome = resolve_outcome(cancelled=cancel.is_set(), error=error)
		if outcome is OperationOutcome.CANCELLED:
			self._publish(item.operation_id, state="stopped", message=_("Operation stopped."))
		elif outcome is OperationOutcome.FAILED:
			message = safe_diagnostic(error)
			self._publish(item.operation_id, state="failed", message=message, error=message)
		else:
			self._publish(item.operation_id, state="succeeded", message={
				"load": _("Model loaded."), "unload": _("Model unloaded."),
				"remove": _("Preset removed."),
			}[item.kind])

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
			for event in self._executing:
				event.set()
			for identifier, event in self._events.items():
				if self._records[identifier].state in ACTIVE:
					event.set()
		self._executor.shutdown(wait=False, cancel_futures=False)


_registries = {}
_registry_lock = threading.Lock()
_shutting_down = False


def get_model_operations(key, *, load, unload, remove=None):
	with _registry_lock:
		if _shutting_down:
			raise RuntimeError(_("Model operations are shutting down."))
		registry = _registries.get(key)
		if registry is None or registry._closed:
			registry = _registries[key] = ModelOperations()
		registry.bind(load=load, unload=unload, remove=remove)
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
