"""Runtime command execution, independent of command-pipe transport."""
from __future__ import annotations

import logging

try:
	from ..core.litert_contract import DEFAULT_LITERT_VERSION
	from ..core.readiness_progress import run_with_readiness_progress
except ImportError:
	from core.litert_contract import DEFAULT_LITERT_VERSION
	from core.readiness_progress import run_with_readiness_progress

logger = logging.getLogger(__name__)


def execute_runtime_command(server, frame, write):
	cmd_type = str(frame.get("type", "") or frame.get("command", ""))
	last_stage = None
	def report_stage(stage):
		nonlocal last_stage
		if stage != last_stage:
			last_stage = stage
			write({"type": "runtime_progress", "stage": stage})
	stage_options = {"on_stage": report_stage} if frame.get("report_readiness_progress") else {}
	if cmd_type == "litert_ensure_ready":
		try:
			executor = server.get_litert_executor()
			config = frame.get("config")
			timeout = float(frame.get("timeout_seconds", 60.0))
			python_exe = frame.get("python_exe") or frame.get("executable")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			host = frame.get("host")
			raw_port = frame.get("port")
			port = int(raw_port) if raw_port is not None else None
			status = run_with_readiness_progress(lambda: executor.ensure_ready(
				config=config,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
				host=host,
				port=port,
			), (lambda _text: None) if frame.get("report_readiness_progress") else None,
				executor.get_status,
				on_stage=lambda stage: write({"type": "runtime_progress", "stage": stage}),
			)
			write(
				{
					"type": "litert_status_response",
					"command": "litert_ensure_ready",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("litert_ensure_ready error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_ensure_ready",
					"error_code": "LITERT_START_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_finalize_upgrade":
		try:
			pending = server.get_litert_executor().finalize_upgrade(str(frame.get("version", DEFAULT_LITERT_VERSION)))
			write({"type": "litert_upgrade_response",
				"command": cmd_type, "success": True, "pending": pending})
		except Exception as exc:
			write({"type": "error", "command": cmd_type,
				"success": False, "error_message": str(exc)})

	elif cmd_type == "litert_stop":
		try:
			executor = server.get_litert_executor()
			timeout = float(frame.get("timeout_seconds", 10.0))
			status = executor.stop(timeout_seconds=timeout)
			write(
				{
					"type": "litert_status_response",
					"command": "litert_stop",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("litert_stop error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_stop",
					"error_code": "LITERT_STOP_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_restart":
		try:
			executor = server.get_litert_executor()
			config = frame.get("config")
			timeout = float(frame.get("timeout_seconds", 60.0))
			python_exe = frame.get("python_exe") or frame.get("executable")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			host = frame.get("host")
			raw_port = frame.get("port")
			port = int(raw_port) if raw_port is not None else None
			status = executor.restart(
				config=config,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
				host=host,
				port=port,
			)
			write(
				{
					"type": "litert_status_response",
					"command": "litert_restart",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("litert_restart error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_restart",
					"error_code": "LITERT_RESTART_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type in ("litert_get_status", "litert_status"):
		try:
			executor = server.get_litert_executor()
			status = executor.get_status()
			write(
				{
					"type": "litert_status_response",
					"command": "litert_get_status",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("litert_get_status error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_get_status",
					"error_code": "LITERT_STATUS_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_adopt":
		try:
			executor = server.get_litert_executor()
			status = executor.adopt()
			write(
				{
					"type": "litert_status_response",
					"command": "litert_adopt",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("litert_adopt error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_adopt",
					"error_code": "LITERT_ADOPT_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_import_model":
		try:
			executor = server.get_litert_executor()
			model_path = frame.get("model_path") or frame.get("source_path")
			model_id = str(frame.get("model_id", ""))
			delete_source = bool(frame.get("delete_source", False))
			timeout = float(frame.get("timeout_seconds", 120.0))
			python_exe = frame.get("python_exe")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			res = executor.import_model(
				model_path=model_path,
				model_id=model_id,
				delete_source=delete_source,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
			)
			write(
				{
					"type": "litert_import_response",
					"command": "litert_import_model",
					"success": True,
					"model_id": model_id,
					"imported_path": res.get("imported_path", ""),
				}
			)
		except Exception as exc:
			logger.error("litert_import_model error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_import_model",
					"error_code": "LITERT_IMPORT_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_import_huggingface_model":
		try:
			executor = server.get_litert_executor()
			repository = str(frame.get("repository", ""))
			artifact = str(frame.get("artifact", ""))
			model_id = str(frame.get("model_id", ""))
			token = frame.get("token") or frame.get("huggingface_token")
			timeout = float(frame.get("timeout_seconds", 600.0))
			python_exe = frame.get("python_exe")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			res = executor.import_huggingface_model(
				repository=repository,
				artifact=artifact,
				model_id=model_id,
				token=token,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
			)
			write(
				{
					"type": "litert_import_response",
					"command": "litert_import_huggingface_model",
					"success": True,
					"model_id": model_id,
				}
			)
		except Exception as exc:
			logger.error("litert_import_huggingface_model error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_import_huggingface_model",
					"error_code": "LITERT_IMPORT_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_delete_model":
		try:
			executor = server.get_litert_executor()
			model_id = str(frame.get("model_id", ""))
			timeout = float(frame.get("timeout_seconds", 60.0))
			python_exe = frame.get("python_exe")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			executor.delete_model(
				model_id=model_id,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
			)
			write(
				{
					"type": "litert_delete_response",
					"command": "litert_delete_model",
					"success": True,
					"model_id": model_id,
				}
			)
		except Exception as exc:
			logger.error("litert_delete_model error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_delete_model",
					"error_code": "LITERT_DELETE_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_rename_model":
		try:
			executor = server.get_litert_executor()
			old_id = str(frame.get("old_id", ""))
			new_id = str(frame.get("new_id", ""))
			timeout = float(frame.get("timeout_seconds", 30.0))
			python_exe = frame.get("python_exe")
			litert_dir = frame.get("litert_dir")
			version = str(frame.get("version", DEFAULT_LITERT_VERSION))
			executor.rename_model(
				old_id=old_id,
				new_id=new_id,
				timeout_seconds=timeout,
				python_exe=python_exe,
				litert_dir=litert_dir,
				version=version,
			)
			write(
				{
					"type": "litert_rename_response",
					"command": "litert_rename_model",
					"success": True,
					"old_id": old_id,
					"new_id": new_id,
				}
			)
		except Exception as exc:
			logger.error("litert_rename_model error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_rename_model",
					"error_code": "LITERT_RENAME_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "litert_list_models":
		try:
			executor = server.get_litert_executor()
			timeout = float(frame.get("timeout_seconds", 5.0))
			litert_dir = frame.get("litert_dir")
			models = executor.list_models(timeout_seconds=timeout, litert_dir=litert_dir)
			write(
				{
					"type": "litert_models_response",
					"command": "litert_list_models",
					"success": True,
					"models": models,
				}
			)
		except Exception as exc:
			logger.error("litert_list_models error: %s", exc)
			write(
				{
					"type": "error",
					"command": "litert_list_models",
					"error_code": "LITERT_LIST_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	# ── llama.cpp Lifecycle & Router Preset Commands ─────────────
	elif cmd_type == "llama_ensure_ready":
		try:
			executor = server.get_llama_executor()
			config = frame.get("config")
			model_id = frame.get("model_id")
			timeout = float(frame.get("timeout_seconds", 60.0))
			host = frame.get("host")
			raw_port = frame.get("port")
			port = int(raw_port) if raw_port is not None else None
			executable = frame.get("executable") or frame.get("server_executable")
			model = frame.get("model")
			models_preset = frame.get("models_preset") or frame.get("preset_path")
			threads = int(frame.get("threads") or 0)
			context = int(frame.get("context") or 0)
			alias = frame.get("alias")
			startup_identity = frame.get("startup_identity")
			status = run_with_readiness_progress(lambda: executor.ensure_ready(
				config=config,
				model_id=model_id,
				timeout_seconds=timeout,
				host=host,
				port=port,
				executable=executable,
				model=model,
				models_preset=models_preset,
				threads=threads,
				context=context,
				alias=alias,
				startup_identity=startup_identity,
			), (lambda _text: None) if frame.get("report_readiness_progress") else None,
				executor.get_status,
				on_stage=lambda stage: write({"type": "runtime_progress", "stage": stage}),
			)
			write(
				{
					"type": "llama_status_response",
					"command": "llama_ensure_ready",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("llama_ensure_ready error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_ensure_ready",
					"error_code": "LLAMA_START_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "llama_stop":
		try:
			executor = server.get_llama_executor()
			timeout = float(frame.get("timeout_seconds", 10.0))
			status = executor.stop(timeout_seconds=timeout)
			write(
				{
					"type": "llama_status_response",
					"command": "llama_stop",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("llama_stop error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_stop",
					"error_code": "LLAMA_STOP_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "llama_restart":
		try:
			executor = server.get_llama_executor()
			config = frame.get("config")
			model_id = frame.get("model_id")
			timeout = float(frame.get("timeout_seconds", 60.0))
			host = frame.get("host")
			raw_port = frame.get("port")
			port = int(raw_port) if raw_port is not None else None
			executable = frame.get("executable") or frame.get("server_executable")
			model = frame.get("model")
			models_preset = frame.get("models_preset") or frame.get("preset_path")
			threads = int(frame.get("threads") or 0)
			context = int(frame.get("context") or 0)
			alias = frame.get("alias")
			startup_identity = frame.get("startup_identity")
			status = executor.restart(
				config=config,
				model_id=model_id,
				timeout_seconds=timeout,
				host=host,
				port=port,
				executable=executable,
				model=model,
				models_preset=models_preset,
				threads=threads,
				context=context,
				alias=alias,
				startup_identity=startup_identity,
			)
			write(
				{
					"type": "llama_status_response",
					"command": "llama_restart",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("llama_restart error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_restart",
					"error_code": "LLAMA_RESTART_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type in ("llama_get_status", "llama_status"):
		try:
			executor = server.get_llama_executor()
			status = executor.get_status()
			write(
				{
					"type": "llama_status_response",
					"command": "llama_get_status",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("llama_get_status error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_get_status",
					"error_code": "LLAMA_STATUS_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "llama_adopt":
		try:
			executor = server.get_llama_executor()
			model_id = frame.get("model_id")
			status = executor.adopt(model_id=model_id)
			write(
				{
					"type": "llama_status_response",
					"command": "llama_adopt",
					"success": True,
					"status": status,
				}
			)
		except Exception as exc:
			logger.error("llama_adopt error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_adopt",
					"error_code": "LLAMA_ADOPT_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type in {"llama_resolve_hf", "llama_resolve_companions", "llama_unload_model"}:
		try:
			executor = server.get_llama_executor()
			if cmd_type == "llama_resolve_hf":
				result = executor.resolve_hf(str(frame.get("repo") or frame.get("repository") or ""), str(frame.get("revision", "main")), str(frame.get("role", "primary")))
			elif cmd_type == "llama_resolve_companions":
				result = executor.resolve_companions(frame.get("companions", []), **stage_options)
			else:
				result = executor.unload_model(str(frame.get("model_id", "")), float(frame.get("timeout_seconds", 30)), **stage_options)
			write({"type": "llama_operation_response", "command": cmd_type, "success": True, "result": result})
		except Exception as exc:
			write({"type": "error", "command": cmd_type, "success": False, "error_message": str(exc)})

	elif cmd_type == "llama_prepare_model":
		try:
			result = server.get_llama_executor().prepare_model(str(frame.get("model_id", "")), float(frame.get("timeout_seconds", 300)), **stage_options)
			write({"type": "llama_prepare_response", "command": cmd_type, **result})
		except Exception as exc:
			write({"type": "error", "command": cmd_type, "success": False, "error_code": "LLAMA_PREPARE_FAILED", "error_message": str(exc)})

	elif cmd_type in {"llama_discover_assets", "llama_verify_asset"}:
		try:
			executor = server.get_model_asset_executor()
			if cmd_type == "llama_discover_assets":
				roots = [*server._default_cache_roots(), *frame.get("roots", [])]
				result = executor.discover_model_assets(roots, frame.get("generation", 0))
			else:
				result = executor.verify_model_asset(str(frame.get("token", "")), role=str(frame.get("role", "primary")))
			write({"type": "llama_assets_response", "command": cmd_type, "success": True, "result": result.to_dict()})
		except Exception as exc:
			write({"type": "error", "command": cmd_type, "success": False, "error_code": "LLAMA_ASSET_FAILED", "error_message": str(exc)})

	elif cmd_type == "llama_inspect_options":
		try:
			options = server.get_llama_executor().inspect_options(str(frame.get("executable") or "llama-server"))
			write({"type": "llama_options_response", "command": cmd_type, "success": True, "options": sorted(options)})
		except Exception as exc:
			write({"type": "error", "command": cmd_type, "success": False, "error_code": "LLAMA_OPTIONS_FAILED", "error_message": str(exc)})

	elif cmd_type == "llama_delete_cache":
		try:
			result = server.get_llama_executor().delete_cache(str(frame.get("cache_root", "")), str(frame.get("path", "")), model_id=frame.get("model_id"))
			write({"type": "llama_delete_cache_response", "command": cmd_type, **result})
		except Exception as exc:
			write({"type": "error", "command": cmd_type, "success": False, "error_code": "LLAMA_CACHE_DELETE_FAILED", "error_message": str(exc)})

	elif cmd_type == "llama_configure_preset":
		try:
			executor = server.get_llama_executor()
			models = frame.get("models", [])
			default_model = frame.get("default_model")
			preset_path = frame.get("preset_path")
			res = executor.configure_preset(
				models=models,
				default_model=default_model,
				preset_path=preset_path,
				executable=frame.get("executable"),
			)
			write(
				{
					"type": "llama_configure_preset_response",
					"command": "llama_configure_preset",
					"success": True,
					"preset_path": res.get("preset_path", ""),
					"sha256": res.get("sha256", ""),
				}
			)
		except Exception as exc:
			logger.error("llama_configure_preset error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_configure_preset",
					"error_code": "LLAMA_PRESET_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	elif cmd_type == "llama_list_models":
		try:
			executor = server.get_llama_executor()
			timeout = float(frame.get("timeout_seconds", 2.0))
			preset_path = frame.get("preset_path")
			models = executor.list_models(timeout_seconds=timeout, preset_path=preset_path)
			write(
				{
					"type": "llama_models_response",
					"command": "llama_list_models",
					"success": True,
					"models": models,
				}
			)
		except Exception as exc:
			logger.error("llama_list_models error: %s", exc)
			write(
				{
					"type": "error",
					"command": "llama_list_models",
					"error_code": "LLAMA_LIST_FAILED",
					"error_message": str(exc),
					"success": False,
				}
			)

	else:
		write(
			{
				"type": "error",
				"error_code": "UNKNOWN_COMMAND",
				"error_message": f"Unknown command type '{cmd_type}'",
			}
		)
