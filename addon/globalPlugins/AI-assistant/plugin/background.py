# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
import logging
from typing import Any, TYPE_CHECKING, cast

from ..core.cancellation import CancellationToken, RequestCancelled, cancellation_scope, check_cancelled
from ..providers.interfaces import LLMProviderError, ProviderConfigurationError
from ..providers.runtime.server import LiteRTServerError, get_litert_supervisor
from ..providers.llama_manager import LlamaCppModelManager
from ..service.error_reporter import ErrorContext, error_reporter
from ..service.llm import LLMService
from ..service.provider_readiness import ProviderReadinessService, get_provider_display_name
from ..config.settings import get_provider, get_model_name
from ..ui import nvda_ui
from ..ui.session_state import build_provider_status_message
from ..use_case.engine import UseCaseEngine
from ..use_case.types import (
	ATTACH_FOCUSED_IMAGE_TO_CHAT,
	OPEN_CHAT,
	OPEN_CHAT_WITH_PAGE_CONTENT,
	OPEN_CHAT_WITH_SCREENSHOT,
	UseCaseId,
)

if TYPE_CHECKING:
	from ..providers.runtime.server import LiteRTServerSupervisor

log = logging.getLogger(__name__)


# Use cases that open a chat workspace without touching the LLM.  They must
# not be gated on LiteRT-LM server readiness (which may be slow or fail), or
# the chat window would never open for a non-inference action.
_NON_LLM_USE_CASES = frozenset(
	{OPEN_CHAT, OPEN_CHAT_WITH_PAGE_CONTENT, OPEN_CHAT_WITH_SCREENSHOT, ATTACH_FOCUSED_IMAGE_TO_CHAT}
)


# Managed runtime lifecycle is centralized in native RuntimeSupervisor (Rust/PyO3).
# _litert_readiness_lock, _litert_restart_lock, _litert_restart_pending, and _llama_readiness_lock are removed.


def ensure_litert_server_ready(on_progress: Callable[[str], None] | None = None) -> None:
	"""Auto-start the LiteRT-LM server if the active provider is litert-lm.

	This is a standalone function so it can be called from both the
	background task runner and the WebView chat adapter.

	The server process starts quickly (~2s) without pre-loading a model.
	The model is loaded lazily by the server on the first inference request.

	Args:
	    on_progress: Optional callback receiving status message strings.

	Raises:
	    LiteRTServerError: If the server cannot be started, fails to
	        become healthy, or the configured model cannot be imported.
	"""
	provider = get_provider()
	log.debug("ensure_litert_server_ready: active provider=%s", provider)
	if provider != "litert-lm":
		log.debug("ensure_litert_server_ready: skipping — not litert-lm")
		return

	_ensure_litert_server_ready_core(on_progress=on_progress)


def _ensure_litert_server_ready_core(
	on_progress: Callable[[str], None] | None = None,
) -> None:
	supervisor = get_litert_supervisor()
	if not supervisor.is_installed:
		log.warning("ensure_litert_server_ready: runtime not installed")
		raise LiteRTServerError(
			"LiteRT-LM runtime is not installed. Please download it from the AI Assistant settings panel."
		)

	if hasattr(supervisor, "ensure_ready"):
		supervisor.ensure_ready(timeout=60.0, on_progress=on_progress)
	else:
		if not supervisor.is_running or not supervisor.matches_current_configuration():
			if supervisor.is_running:
				supervisor.stop()
			supervisor.start(on_progress=on_progress)
		supervisor.wait_until_ready(timeout=60.0, on_progress=on_progress)

	# Ensure the configured model is registered with the server.
	_ensure_model_imported(supervisor, on_progress=on_progress)


def ensure_provider_server_ready(on_progress: Callable[[str], None] | None = None) -> None:
	"""Ensure the active managed local provider server is ready."""
	provider = get_provider()
	if provider == "litert-lm":
		ensure_litert_server_ready(on_progress=on_progress)
		# Startup discovery may have run before the managed server was ready.
		# Refresh the shared catalog after readiness so model selection sees the
		# server's actual model list immediately.
		from ..service.model_cache import model_catalog_cache

		model_catalog_cache.refresh_async(provider)
		return
	if provider != "llama-cpp-server":
		return
	from ..config.settings import get_active_provider_config

	config = get_active_provider_config()
	manager = LlamaCppModelManager(config=config)
	model_name = str(config.model_name or "").strip()
	record = manager.find_record(model_name) if model_name else None
	if record is None:
		raise LLMProviderError(f"Unknown llama.cpp model: {config.model_name}")
	manager.ensure_running(record, on_progress=on_progress)
	from ..service.model_cache import model_catalog_cache

	model_catalog_cache.refresh_async(provider)


def _ensure_model_imported(
	supervisor: LiteRTServerSupervisor,
	on_progress: Callable[[str], None] | None = None,
) -> None:
	"""Check that the configured model is registered in the server catalog.

	If the model file exists locally but is not yet imported, run
	``litert-lm import`` to register it.  When the model has platform
	variants (CPU, GPU, etc.) the best downloaded variant is imported
	(GPU preferred on GPU-capable machines, CPU otherwise).

	The stored model name is normalised through
	:func:`~providers.litert_models.resolve_identity` so that old
	configurations storing bare filenames are transparently migrated
	to canonical HuggingFace model IDs.
	"""
	from ..providers.litert_models import resolve_identity as _resolve
	from ..providers.litert_models import lookup_model as _lookup
	from ..providers.litert_models import build_import_candidates
	from ..providers.runtime.model_download import ModelDownloadService

	raw_model_name = get_model_name()
	if not raw_model_name:
		raise LiteRTServerError(
			"No model configured for LiteRT-LM. Please select a model in the AI Assistant settings."
		)

	# Normalise to canonical model_id (handles legacy filename storage).
	model_id = _resolve(raw_model_name)

	server_models = supervisor.list_server_models()
	log.debug(
		"_ensure_model_imported: raw=%s canonical=%s server_models=%s",
		raw_model_name,
		model_id,
		server_models,
	)

	# The HTTP model list alone is not authoritative: an unrelated
	# LiteRT-LM process may be answering on the configured port while using
	# the user's global ~/.litert-lm registry.  Require the selected model to
	# exist in the add-on-owned registry as well.
	catalog_dir = supervisor.catalog_model_dir(model_id)
	catalog_model = catalog_dir / "model.litertlm" if catalog_dir is not None else None
	if catalog_model is not None and catalog_model.is_file():
		if model_id in server_models:
			log.debug("_ensure_model_imported: model already registered")
			return
		raise LiteRTServerError(
			f"LiteRT-LM server at {supervisor.base_url} is not using the "
			"AI Assistant model registry. Stop the existing server and try again."
		)

	# Model is not in the add-on-owned registry.  Importing copies the model
	# into that registry; it does not merely register the original path.
	# This must happen before accepting a model reported by /v1/models.
	if model_id in server_models:
		log.debug(
			"_ensure_model_imported: server reports %s but its add-on registry "
			"copy is missing; repairing the registry",
			model_id,
		)

	# Model not registered — find a downloaded file to import.
	definition = _lookup(model_id)
	svc = ModelDownloadService()

	# Build a priority-ordered list of filenames to try: recommended
	# variant first, then other variants, then the primary file.
	candidate_filenames = build_import_candidates(definition)

	for filename in candidate_filenames:
		if svc.is_downloaded(filename):
			local_path = svc.model_path(filename)
			log.debug(
				"_ensure_model_imported: importing %s as %s...",
				local_path,
				model_id,
			)
			supervisor.import_model(
				local_path,
				model_id,
				on_progress=on_progress,
			)
			if model_id not in supervisor.list_server_models():
				raise LiteRTServerError(
					f"LiteRT-LM imported {model_id}, but the running server "
					"cannot see the add-on-owned model registry."
				)
			return

	# File not found — user needs to download first.
	raise LiteRTServerError(
		f"Model {model_id} is not downloaded. "
		"Please open the Model Manager from the AI Assistant menu "
		"to download it."
	)



def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class BackgroundTaskRunner:
	def __init__(
		self,
		llm_service: LLMService,
		use_case_engine: UseCaseEngine,
		progress_handler: Callable[[Any], None],
		error_handler: Callable[[str, str], None] | None = None,
		readiness_service: ProviderReadinessService | None = None,
	) -> None:
		self._llm_service = llm_service
		self._use_case_engine = use_case_engine
		self._progress_handler = progress_handler
		self._error_handler = error_handler
		self._readiness_service = readiness_service or ProviderReadinessService()
		self._closed = threading.Event()
		self._threads: set[threading.Thread] = set()
		self._threads_lock = threading.Lock()
		# Keep completed requests cancellable until their queued UI delivery runs.
		self._requests: dict[CancellationToken, int] = {}
		self._finished_requests: set[CancellationToken] = set()

	def close(self) -> None:
		"""Stop requests and delivery without waiting for provider transport."""
		self._closed.set()
		self.cancel_active_requests()

	def cancel_active_requests(self) -> int:
		with self._threads_lock:
			tokens = [token for token in self._requests if not token.cancelled]
			for token in tokens:
				token.cancel()
		return len(tokens)

	def _can_deliver(self, token: CancellationToken) -> bool:
		return not self._closed.is_set() and not token.cancelled

	def _release_request_locked(self, token: CancellationToken) -> None:
		if token in self._finished_requests and self._requests.get(token, 0) == 0:
			self._requests.pop(token, None)
			self._finished_requests.discard(token)

	def _retain_delivery(self, token: CancellationToken) -> None:
		with self._threads_lock:
			self._requests[token] = self._requests.get(token, 0) + 1

	def _release_delivery(self, token: CancellationToken) -> None:
		with self._threads_lock:
			self._requests[token] = self._requests.get(token, 1) - 1
			self._release_request_locked(token)

	def _queue_delivery(self, token: CancellationToken, callback: Callable[..., None], *args: Any) -> None:
		if not self._can_deliver(token):
			return
		with self._threads_lock:
			self._requests[token] = self._requests.get(token, 0) + 1

		def deliver() -> None:
			try:
				if self._can_deliver(token):
					with cancellation_scope(token):
						callback(*args)
			finally:
				with self._threads_lock:
					self._requests[token] = self._requests.get(token, 1) - 1
					self._release_request_locked(token)
		try:
			nvda_ui.queue(deliver)
		except Exception:
			with self._threads_lock:
				self._requests[token] -= 1
				self._release_request_locked(token)
			raise

	def _start_worker(self, *, target: Callable[[], None], name: str, token: CancellationToken | None = None) -> bool:
		token = token or CancellationToken()
		def tracked_target() -> None:
			try:
				if self._can_deliver(token):
					with cancellation_scope(token):
						target()
			finally:
				with self._threads_lock:
					self._threads.discard(threading.current_thread())
					self._finished_requests.add(token)
					self._release_request_locked(token)

		thread = threading.Thread(target=tracked_target, name=name, daemon=True)
		with self._threads_lock:
			if self._closed.is_set():
				return False
			self._threads.add(thread)
			self._requests[token] = 0
			token.bind_delivery_lifetime(
				lambda: self._retain_delivery(token), lambda: self._release_delivery(token),
			)
		try:
			thread.start()
		except Exception:
			with self._threads_lock:
				self._threads.discard(thread)
				self._requests.pop(token, None)
			raise
		return True

	def _report_error(self, token: CancellationToken, error: Exception, context: ErrorContext, title: str = "") -> None:
		if not self._can_deliver(token):
			return
		def present(presentation) -> None:
			if self._error_handler is not None and title:
				self._queue_delivery(token, self._error_handler, title, presentation.message)
			else:
				self._queue_delivery(token, nvda_ui.message, f"{presentation.title}: {presentation.message}")
		error_reporter.report(error, context, owner=present)

	def start_model_preload(self) -> None:
		def worker(token: CancellationToken) -> None:
			provider = get_provider()
			try:
				check_cancelled()
				readiness = self._readiness_service.evaluate_active()
				provider = readiness.provider
				check_cancelled()
				if not readiness.can_infer:
					log.debug("Skipping model preload for %s; provider is not ready", provider)
					return
				provider_name = get_provider_display_name(provider)
				# TRANSLATORS: Spoken while checking model availability. {provider} is the provider name.
				self._queue_delivery(token, nvda_ui.message, _("Checking {provider} model availability.").format(provider=provider_name))
				model = self._llm_service.ensure_model_available(
					on_progress=lambda text: self._queue_delivery(token, nvda_ui.message, text)
				)
				check_cancelled()
			except RequestCancelled:
				return
			except Exception as error:
				self._report_error(token, error, ErrorContext(operation="model preload", provider=provider, origin="background preload", optional=True))
			else:
				# TRANSLATORS: Spoken when a provider model is ready. {provider} and {model} are their names.
				self._queue_delivery(token, nvda_ui.message, _("{provider} model {model} is ready.").format(provider=provider_name, model=model))

		token = CancellationToken()
		self._start_worker(target=lambda: worker(token), name="BrowserAssistantModelPreload", token=token)

	def run_use_case_in_background(
		self, use_case_id: UseCaseId, title: str, render_result: Callable[[Any], None]
	) -> None:
		def worker(token: CancellationToken) -> None:
			try:
				check_cancelled()
				if use_case_id not in _NON_LLM_USE_CASES:
					preparing = threading.Event()
					preparing.set()
					def report_preparation(message: str) -> None:
						def deliver() -> None:
							if not preparing.is_set():
								return
							from ..config.settings import get_one_shot_output_mode
							if get_one_shot_output_mode() != "display_only":
								nvda_ui.message(message)
						self._queue_delivery(token, deliver)
					try:
						ensure_provider_server_ready(on_progress=report_preparation)
					finally:
						preparing.clear()
				check_cancelled()
				result = self._use_case_engine.execute(
					use_case_id,
					progress=lambda event: self._queue_delivery(token, self._progress_handler, event),
				)
				check_cancelled()
			except RequestCancelled:
				return
			except ProviderConfigurationError as error:
				if not self._can_deliver(token):
					return
				readiness = self._readiness_service.evaluate_active()
				message = build_provider_status_message(_, readiness) or _("The selected provider is not fully configured.")
				self._report_error(token, error if str(error).strip() else ProviderConfigurationError(message), ErrorContext(operation=str(use_case_id), origin="use case"), title)
				return
			except Exception as error:
				self._report_error(token, error, ErrorContext(operation=str(use_case_id), origin="use case"), title)
				return
			self._queue_delivery(token, render_result, result)

		token = CancellationToken()
		self._start_worker(target=lambda: worker(token), name=f"AIassistant{title.replace(' ', '')}Worker", token=token)
