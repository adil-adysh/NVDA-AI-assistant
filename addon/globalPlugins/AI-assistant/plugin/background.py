# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import Any, TYPE_CHECKING, cast

from logHandler import log

from ..providers.interfaces import LLMProviderError, ProviderConfigurationError
from ..providers.runtime.server import LiteRTServerError, get_litert_supervisor
from ..providers.runtime.llama_server import shutdown_llama_servers
from ..providers.llama_manager import LlamaCppModelManager
from ..service.error_reporter import ErrorContext, error_reporter
from ..service.llm import LLMService
from ..service.provider_readiness import ProviderReadinessService, get_provider_display_name
from ..config.settings import get_provider, get_model_name
from ..config.state import (
	subscribe_litert_server_config_change,
	subscribe_llama_server_config_change,
)
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


# Use cases that open a chat workspace without touching the LLM.  They must
# not be gated on LiteRT-LM server readiness (which may be slow or fail), or
# the chat window would never open for a non-inference action.
_NON_LLM_USE_CASES = frozenset(
	{OPEN_CHAT, OPEN_CHAT_WITH_PAGE_CONTENT, OPEN_CHAT_WITH_SCREENSHOT, ATTACH_FOCUSED_IMAGE_TO_CHAT}
)


# Managed runtime lifecycle is centralized in native RuntimeSupervisor (Rust/PyO3).
# _litert_readiness_lock, _litert_restart_lock, _litert_restart_pending, and _llama_readiness_lock are removed.


def _on_litert_server_config_changed() -> None:
	"""Queue a LiteRT server restart when engine settings changed.

	Fired from the config layer (NVDA main thread) whenever a
	server-relevant setting — backend, cache, cpu thread count, num_ctx
	or the active model — is persisted.  The actual stop/start is
	deferred to a daemon worker so the dialog that saved the setting
	never blocks on a server restart.
	"""
	supervisor = get_litert_supervisor()
	status = supervisor.status()
	if not status.is_running:
		if status.is_adopted:
			# An adopted server has no process handle we can stop, so it
			# cannot be restarted here. Regenerate config.json so the next
			# start uses the new settings and surface the limitation.
			try:
				supervisor.sync_config()
			except Exception as error:
				error_reporter.report(
					error,
					ErrorContext(operation="regenerate LiteRT configuration", provider="litert-lm", origin="server configuration"),
				)
			log.warning(
				"LiteRT engine settings changed but the server was adopted "
				"(no process handle). Stop the server or restart NVDA to apply."
			)
		return

	threading.Thread(
		target=_restart_litert_server_worker,
		name="litert-restart-on-config-change",
		daemon=True,
	).start()


def _restart_litert_server_worker() -> None:
	"""Worker thread body performing the deferred LiteRT server restart."""
	try:
		supervisor = get_litert_supervisor()
		log.info("LiteRT engine settings changed; restarting server to apply")
		supervisor.restart(timeout=60.0)
	except Exception as error:
		error_reporter.report(
			error,
			ErrorContext(operation="restart LiteRT server", provider="litert-lm", origin="server configuration"),
		)


subscribe_litert_server_config_change(_on_litert_server_config_changed)


def _on_llama_server_config_changed() -> None:
	"""Stop stale llama-server instances after endpoint/config changes."""
	threading.Thread(
		target=shutdown_llama_servers,
		name="llama-shutdown-on-config-change",
		daemon=True,
	).start()


subscribe_llama_server_config_change(_on_llama_server_config_changed)


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
		available_records = manager._catalog.list_records()
		if available_records:
			record = available_records[0]
			log.info(
				"Configured llama.cpp model %r not found; starting server with %r from preset catalog",
				model_name,
				record.model_id,
			)
			try:
				from ..config.settings import set_model_name
				set_model_name(record.model_id)
			except Exception:
				pass
		else:
			raise LLMProviderError(f"Unknown llama.cpp model: {config.model_name}")
	manager.ensure_running(record, on_progress=on_progress)
	from ..service.model_cache import model_catalog_cache

	model_catalog_cache.refresh_async(provider)


def _ensure_litert_server_ready_locked(
	on_progress: Callable[[str], None] | None = None,
) -> None:
	"""Deprecated alias preserved for test double compatibility."""
	_ensure_litert_server_ready_core(on_progress=on_progress)


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
	candidate_filenames = _build_import_candidates(definition)

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


def _build_import_candidates(definition: object | None) -> list[str]:
	"""Return an ordered list of filenames to try for import.

	GPU variants come first on GPU-capable hardware, then CPU variants,
	then the primary file.  This ensures the best available variant is
	imported automatically.
	"""
	if definition is None or not hasattr(definition, "has_variants"):
		return [definition.filename] if definition is not None else []

	primary = getattr(definition, "filename", "")
	variants: tuple = getattr(definition, "variants", ())
	if not variants:
		return [primary] if primary else []

	from ..providers.litert_models import has_gpu

	gpu_files: list[str] = []
	cpu_files: list[str] = []

	for v in variants:
		fn = getattr(v, "filename", "")
		if not fn:
			continue
		pf: str = getattr(v, "platform_hint", "cpu")
		if pf == "gpu":
			gpu_files.append(fn)
		else:
			cpu_files.append(fn)

	if has_gpu():
		result = gpu_files + cpu_files
	else:
		result = cpu_files + gpu_files

	if primary and primary not in result:
		result.append(primary)
	return result if result else ([primary] if primary else [])


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

	def close(self) -> None:
		"""Cancel delivery from current jobs and reject new background work.

		Provider shutdown owns interruption of blocking network/native calls.  This
		method is deliberately non-blocking because NVDA termination must not wait
		for those calls, but workers that finish later cannot enqueue UI updates.
		"""
		self._closed.set()

	def _start_worker(self, *, target: Callable[[], None], name: str) -> bool:
		if self._closed.is_set():
			return False

		def tracked_target() -> None:
			try:
				if not self._closed.is_set():
					target()
			finally:
				with self._threads_lock:
					self._threads.discard(threading.current_thread())

		thread = threading.Thread(target=tracked_target, name=name, daemon=True)
		with self._threads_lock:
			if self._closed.is_set():
				return False
			self._threads.add(thread)
		thread.start()
		return True

	def start_model_preload(self) -> None:
		def worker() -> None:
			provider = get_provider()
			try:
				readiness = self._readiness_service.evaluate_active()
				provider = readiness.provider
				if self._closed.is_set() or not readiness.can_infer:
					log.debug("Skipping model preload for %s; provider is not ready", readiness.provider)
					return
				provider_name = get_provider_display_name(readiness.provider)
				# TRANSLATORS: Message spoken while checking model availability for a provider. {provider} is replaced with the provider name.
				if not self._closed.is_set():
					nvda_ui.queue(
						nvda_ui.message,
						_("Checking {provider} model availability.").format(provider=provider_name),
					)
				model = self._llm_service.ensure_model_available(
					on_progress=lambda text: (
						nvda_ui.queue(nvda_ui.message, text) if not self._closed.is_set() else None
					)
				)
			except Exception as error:
				error_reporter.report(
					error,
					ErrorContext(operation="model preload", provider=provider, origin="background preload", optional=True),
				)
			else:
				if self._closed.is_set():
					return
				# TRANSLATORS: Message spoken when a provider model is confirmed ready. {provider} and {model} are replaced with the provider and model names.
				nvda_ui.queue(
					nvda_ui.message,
					_("{provider} model {model} is ready.").format(provider=provider_name, model=model),
				)

		self._start_worker(target=worker, name="BrowserAssistantModelPreload")

	def run_use_case_in_background(
		self, use_case_id: UseCaseId, title: str, render_result: Callable[[Any], None]
	) -> None:
		def worker() -> None:
			log.debug("BackgroundTaskRunner worker starting use_case_id=%s title=%s", use_case_id, title)
			try:
				if self._closed.is_set():
					return
				if use_case_id not in _NON_LLM_USE_CASES:
					ensure_provider_server_ready(
						on_progress=lambda msg: (
							nvda_ui.queue(nvda_ui.message, msg) if not self._closed.is_set() else None
						),
					)
				if self._closed.is_set():
					return
				result = self._use_case_engine.execute(use_case_id, progress=self._progress_handler)
			except ProviderConfigurationError as error:
				log.exception(
					f"BackgroundTaskRunner blocked by provider configuration for use case {use_case_id}"
				)
				readiness = self._readiness_service.evaluate_active()
				# TRANSLATORS: Message spoken when the selected provider is not fully configured for the requested operation.
				message = build_provider_status_message(_, readiness) or _(
					"The selected provider is not fully configured."
				)
				error_reporter.report(
					ProviderConfigurationError(message) if not str(error).strip() else error,
					ErrorContext(operation=str(use_case_id), origin="use case"),
					owner=(lambda p: self._error_handler(title, p.message)) if self._error_handler else None,
				)
				return
			except LiteRTServerError as error:
				log.exception(f"BackgroundTaskRunner LiteRT server error for use case {use_case_id}")
				error_reporter.report(
					error,
					ErrorContext(operation=str(use_case_id), origin="use case"),
					owner=(lambda p: self._error_handler(title, p.message)) if self._error_handler else None,
				)
				return
			except Exception as error:
				log.exception(f"BackgroundTaskRunner failed executing use case {use_case_id}")
				error_reporter.report(
					error,
					ErrorContext(operation=str(use_case_id), origin="use case"),
					owner=(lambda p: self._error_handler(title, p.message)) if self._error_handler else None,
				)
				return

			if not self._closed.is_set():
				nvda_ui.queue(render_result, result)

		if self._start_worker(target=worker, name=f"AIassistant{title.replace(' ', '')}Worker"):
			log.debug("BackgroundTaskRunner started thread for use_case_id=%s title=%s", use_case_id, title)
