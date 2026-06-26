# -*- coding: utf-8 -*-
"""LiteRT-LM provider — wraps litert_lm Python API as an LLMProvider.

Loads the litert_lm runtime on demand via ``RuntimeManager`` (injected
or created lazily), then delegates to ``litert_lm.Engine`` for model
loading and inference.

Models are either user-specified paths (existing behaviour) or
downloaded from Hugging Face via ``ModelDownloadService`` and cached
under ``%APPDATA%/nvda/AIAssistant/models/litert-lm/``.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from logHandler import log

from ...core.canonical import Message, Part, Tool
from ...core.messages import LLMResponse, SummaryResponse
from ..config import LiteRTConfig
from ..interfaces import (
    LLMProvider,
    LLMProviderError,
    MissingModelError,
    PartialCallback,
    ProgressCallback,
    ProviderModelInfo,
    SamplingDefaults,
)
from ..litert_models import KNOWN_MODELS, LiteRTModelDef, download_url, lookup_model
from ..runtime import (
    ModelDownloadError,
    ModelDownloadService,
    RuntimeConfig,
    RuntimeManager,
)


class LiteRTLMProvider(LLMProvider):
    """Provider wrapping the litert-lm local inference engine.

    Parameters:
        config: Provider configuration (runtime version, model path, etc.).
        runtime_manager: Optional ``RuntimeManager``. Created on first
            use if omitted.
        model_download_service: Optional ``ModelDownloadService``.
            Created on first use if omitted.
    """

    _RUNTIME_VERSION = "0.13.1"

    _SUPPORTED_CAPABILITIES = (
        "completion", "chat", "streaming",
        "text_input", "text_output",
    )

    def __init__(
        self,
        config: LiteRTConfig,
        runtime_manager: RuntimeManager | None = None,
        model_download_service: ModelDownloadService | None = None,
    ) -> None:
        self._config = config
        self._runtime_manager = runtime_manager
        self._model_download_service = model_download_service
        self._litert_lm: Any = None  # The imported litert_lm module
        self._engine: Any = None  # litert_lm.Engine instance
        self._loaded = False

    # ── LLMProvider interface ────────────────────────────────────────

    def provider_name(self) -> str:
        return "litert-lm"

    def supports_streaming(self) -> bool:
        return True

    def supports_image_description(self) -> bool:
        return _is_vision_model(self._config.model_name)

    def list_models(self) -> tuple[ProviderModelInfo, ...]:
        """Return known and locally cached models.

        Combines the hardcoded ``KNOWN_MODELS`` registry with any
        additional ``.litertlm`` files found in the cache directory.
        """
        result: list[ProviderModelInfo] = []
        seen: set[str] = set()

        # 1. Known models (registry)
        for known in KNOWN_MODELS:
            info = _model_def_to_info(known)
            result.append(info)
            seen.add(known.model_id)

        # 2. Locally cached models not already covered
        svc = self._model_download_service or ModelDownloadService()
        cache_dir = svc.model_path("")  # just to get the parent
        cache_parent = cache_dir.parent  # litert-lm dir
        if cache_parent.exists():
            for f in sorted(cache_parent.iterdir()):
                if f.suffix == ".litertlm" and f.stem not in seen:
                    result.append(
                        ProviderModelInfo(
                            id=f.stem,
                            provider="litert-lm",
                            display_name=f.stem,
                            capabilities=self._SUPPORTED_CAPABILITIES,
                        )
                    )
                    seen.add(f.stem)

        return tuple(result)

    def get_model_info(
        self, model_name: str | None = None
    ) -> ProviderModelInfo | None:
        resolved = model_name or self._config.model_name
        if not resolved:
            return None

        # Known model?
        known = lookup_model(resolved)
        if known:
            return _model_def_to_info(known)

        # Local file?
        p = Path(resolved)
        if p.suffix == ".litertlm":
            return ProviderModelInfo(
                id=resolved,
                provider="litert-lm",
                display_name=p.stem,
                capabilities=self._SUPPORTED_CAPABILITIES,
            )

        return None

    def ensure_model_available(
        self, on_progress: ProgressCallback | None = None
    ) -> str | None:
        """Ensure the runtime is loaded and the model file is on disk."""
        log.debug(
            "ensure_model_available: model_name=%r",
            self._config.model_name,
        )

        self._ensure_runtime_loaded(on_progress=on_progress)

        model_name = self._config.model_name
        if not model_name:
            log.warning("ensure_model_available: no model configured")
            return None

        # Absolute / existing path → use directly
        resolved = Path(model_name)
        if resolved.is_absolute() and resolved.exists():
            log.debug("ensure_model_available: using absolute path %s", resolved)
            return str(resolved)

        # Try known model
        known = lookup_model(model_name)
        if known is not None:
            log.debug(
                "ensure_model_available: known model %s", known.display_name,
            )
            return self._download_if_needed(known, on_progress=on_progress)

        # Try cache directory
        svc = self._model_download_service or ModelDownloadService()
        cached = svc.model_path(model_name)
        if cached.exists():
            log.debug("ensure_model_available: cached at %s", cached)
            return str(cached)

        # Last resort: try treating the config value as a model_id
        for m in KNOWN_MODELS:
            if m.model_id == model_name or m.filename == model_name:
                log.debug(
                    "ensure_model_available: matched id/filename %s", m.display_name,
                )
                return self._download_if_needed(m, on_progress=on_progress)

        log.warning(
            "ensure_model_available: model NOT FOUND — %s", model_name,
        )
        return None

    def summarize(
        self,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        self._ensure_runtime_loaded()
        return self._generate_internal(
            messages=[
                Message(
                    role="user",
                    parts=(Part(type="text", text=prompt),),
                )
            ],
            stream_handler=stream_handler,
        )

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        self._ensure_runtime_loaded()
        if not _is_vision_model(self._config.model_name):
            raise LLMProviderError(
                "The selected LiteRT-LM model does not support image input. "
                "Choose a vision-capable model (e.g. Gemma 4 E2B or E4B)."
            )
        return self._generate_image_internal(
            image_base64=image_base64,
            prompt=prompt,
            stream_handler=stream_handler,
        )

    def generate(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> LLMResponse:
        self._ensure_runtime_loaded()
        return self._generate_chat(
            messages=messages,
            tools=tools,
            stream_handler=stream_handler,
        )

    def close(self) -> None:
        self._close_engine()

    # ── Internal helpers ─────────────────────────────────────────────

    def _ensure_runtime_loaded(
        self, on_progress: ProgressCallback | None = None
    ) -> None:
        """Lazy-load the litert_lm runtime via RuntimeManager."""
        if self._loaded and self._litert_lm is not None:
            log.debug("LiteRT-LM runtime already loaded")
            return

        version = self._RUNTIME_VERSION
        log.debug("LiteRT-LM runtime NOT loaded; loading version %s", version)

        if self._runtime_manager is None:
            log.debug("Creating new RuntimeManager")
            self._runtime_manager = RuntimeManager()

        config = RuntimeConfig.for_runtime(
            runtime="litert-lm",
            version=version,
        )

        try:
            self._litert_lm = self._runtime_manager.load(
                config, on_progress=on_progress
            )
            self._loaded = True
            log.debug(
                "LiteRT-LM runtime ready — module=%s, file=%s",
                self._litert_lm.__name__,
                getattr(self._litert_lm, "__file__", "?"),
            )
        except Exception as exc:
            log.error(
                "LiteRT-LM runtime load FAILED — version=%s, error=%s",
                version, exc,
            )
            import traceback
            log.error("Traceback:\n%s", traceback.format_exc())
            raise LLMProviderError(
                f"Failed to load LiteRT-LM runtime: {exc}"
            ) from exc

    def _ensure_engine_created(self) -> None:
        """Create the litert_lm.Engine if not already open."""
        if self._engine is not None:
            log.debug("LiteRT-LM engine already exists")
            return

        model_path = self._resolve_model_path()
        if not model_path:
            log.error("LiteRT-LM engine cannot be created — no model path resolved")
            log.error(
                "  config.model_name=%r, runtime loaded=%s, has Engine attr=%s",
                self._config.model_name,
                self._loaded,
                hasattr(self._litert_lm, "Engine") if self._litert_lm else "N/A",
            )
            raise MissingModelError("No LiteRT-LM model path configured")

        backend = self._build_backend()
        vision_backend = self._build_vision_backend(backend)

        log.debug(
            "Creating LiteRT-LM Engine — path=%s, backend=%s, vision_backend=%s, "
            "num_ctx=%s, max_output_tokens=%s",
            model_path,
            backend.get_name() if backend else "default",
            vision_backend.get_name() if vision_backend else "same-as-backend",
            self._config.num_ctx, self._config.generate_max_tokens,
        )

        try:
            self._engine = self._litert_lm.Engine(
                str(model_path),
                backend=backend,
                max_num_tokens=self._config.num_ctx,
                vision_backend=vision_backend,
            )
            log.debug("LiteRT-LM engine created for %s", model_path)
        except Exception as exc:
            log.error(
                "LiteRT-LM engine creation FAILED — path=%s, backend=%s, error=%s",
                model_path, self._config.backend, exc,
            )
            import traceback
            log.error("Traceback:\n%s", traceback.format_exc())
            raise LLMProviderError(
                f"Failed to create LiteRT-LM engine: {exc}"
            ) from exc

    def _build_backend(self) -> Any:
        """Build the litert-lm Backend from config."""
        backend_name = (self._config.backend or "cpu").strip().lower()
        if backend_name == "gpu":
            log.debug("Using GPU backend")
            return self._litert_lm.Backend.GPU()
        log.debug("Using CPU backend")
        return self._litert_lm.Backend.CPU()

    def _build_vision_backend(self, backend: Any) -> Any | None:
        """Build vision backend — separate GPU for vision when using GPU.

        When GPU is selected, uses a dedicated GPU backend for vision
        encoding.  When CPU is selected, vision uses the same CPU backend
        (pass ``None`` so the Engine defaults to the main backend).
        """
        backend_name = (self._config.backend or "cpu").strip().lower()
        if backend_name == "gpu":
            log.debug("Using separate GPU vision backend")
            return self._litert_lm.Backend.GPU()
        return None

    def _close_engine(self) -> None:
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:
                log.debug("Error closing LiteRT-LM engine", exc_info=True)
            self._engine = None

    def _resolve_model_path(self) -> Path | None:
        """Return the model path, downloading if necessary."""
        model_name = self._config.model_name
        log.debug(
            "_resolve_model_path: model_name=%r", model_name,
        )

        if not model_name:
            log.warning("_resolve_model_path: no model configured")
            return None

        # Absolute / existing path
        resolved = Path(model_name)
        if resolved.is_absolute():
            exists = resolved.exists()
            log.debug(
                "  absolute path: %s (exists=%s)", resolved, exists,
            )
            if exists:
                return resolved

        # Known model
        known = lookup_model(model_name)
        if known is not None:
            log.debug(
                "  matched known model: %s (file=%s)",
                known.display_name, known.filename,
            )
            return self._download_if_needed(known)

        # Cache directory
        svc = self._model_download_service or ModelDownloadService()
        cached = svc.model_path(model_name)
        log.debug("  cache path: %s (exists=%s)", cached, cached.exists())
        if cached.exists():
            return cached

        # Last resort: iterate known models
        for m in KNOWN_MODELS:
            if m.model_id == model_name or m.filename == model_name:
                log.debug("  matched known model by id/filename: %s", m.display_name)
                return self._download_if_needed(m)

        log.warning(
            "LiteRT-LM model NOT FOUND — model_name=%r, checked: "
            "absolute=%s, known=%s, cache=%s",
            model_name,
            resolved if resolved.is_absolute() else "N/A",
            known is not None,
            cached.exists(),
        )
        return resolved  # let Engine raise if it's invalid

    def _download_if_needed(
        self,
        model: LiteRTModelDef,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Download *model* if not already cached."""
        svc = self._model_download_service or ModelDownloadService()
        url = download_url(model)

        log.debug(
            "Downloading model — display=%s, file=%s, url=%s",
            model.display_name, model.filename, url,
        )

        try:
            result = svc.download(
                model_name=model.filename,
                url=url,
                on_progress=on_progress,
            )
            log.debug("Model downloaded/cached at: %s", result)
            return result
        except ModelDownloadError as exc:
            log.error(
                "Model download FAILED — display=%s, error=%s",
                model.display_name, exc,
            )
            raise LLMProviderError(
                f"Failed to download model {model.display_name}: {exc}"
            ) from exc

    @staticmethod
    def _convert_single_message(msg: Message) -> dict:
        """Convert a canonical Message to a litert-lm content dict.

        Returns:
            A dict like ``{"role": "user", "content": [{"type": "text", "text": "..."}, ...]}``.
        """
        content: list[dict[str, Any]] = []
        for part in msg.parts:
            if part.type == "text" and part.text:
                content.append({"type": "text", "text": part.text})
            elif part.type == "image" and part.image:
                content.append({
                    "type": "image",
                    "blob": base64.b64encode(part.image).decode("utf-8"),
                })
        if not content:
            # Fallback: treat parts as plain text
            texts = [p.text for p in msg.parts if p.text]
            return {"role": msg.role, "content": "\n".join(texts) if texts else ""}
        return {"role": msg.role, "content": content}

    @staticmethod
    def _convert_history(messages: list[Message]) -> list[dict]:
        """Convert canonical Messages to a list of litert-lm content dicts."""
        return [LiteRTLMProvider._convert_single_message(m) for m in messages]

    @staticmethod
    def _extract_response_text(response: dict) -> str:
        """Extract concatenated text from a litert-lm response dict.

        Expected format: ``{"role": "assistant", "content": [{"type": "text", "text": "..."}]}``
        """
        content = response.get("content", [])
        if isinstance(content, list):
            texts = [
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            return "".join(texts)
        return str(content) if content else ""

    def _generate_text(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> str:
        """Run inference with full conversation history and optional tools.

        * All messages except the last are passed as conversation preface.
        * The last message is sent as the active turn.
        * Tools are wired to the conversation so the model can use them.
        """
        self._ensure_engine_created()

        # Build conversation with history and tools
        history = self._convert_history(messages[:-1]) if len(messages) > 1 else None
        litert_tools = (
            [_LiteRTToolAdapter(t) for t in tools] if tools else None
        )

        conversation = self._engine.create_conversation(
            messages=history,
            tools=litert_tools,
        )

        # Prepare the active turn — last message or fallback to extracted text
        if messages:
            last_msg = self._convert_single_message(messages[-1])
        else:
            last_msg = {"role": "user", "content": ""}

        log.debug(
            "Conversation created, history=%d msgs, tools=%s, streaming=%s, last_role=%s",
            len(history) if history else 0,
            bool(litert_tools),
            stream_handler is not None,
            last_msg.get("role"),
        )

        with conversation:
            if stream_handler is not None:
                full_text: list[str] = []
                cumulative_chars = 0
                for chunk in conversation.send_message_async(last_msg):
                    text_piece = self._extract_response_text(chunk)
                    if text_piece:
                        full_text.append(text_piece)
                        cumulative_chars += len(text_piece)
                        stream_handler(text_piece, cumulative_chars)

                combined = "".join(full_text)
                log.debug(
                    "Streaming done: %d chars in %d chunks",
                    len(combined), len(full_text),
                )
                return combined
            else:
                result = conversation.send_message(last_msg)
                text = self._extract_response_text(result)
                log.debug(
                    "Non-streaming done: %d chars, response keys=%s",
                    len(text), list(result.keys()),
                )
                return text

    def _generate_image_internal(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> SummaryResponse:
        """Describe an image and return a SummaryResponse.

        Builds a canonical ``Message`` with text + image parts and
        delegates to ``_generate_text`` (which handles history, tools,
        streaming, and the ``Engine`` lifecycle).
        """
        log.debug(
            "_generate_image_internal: image_bytes=%d, prompt=%r, streaming=%s",
            len(base64.b64decode(image_base64)) if image_base64 else 0,
            prompt[:80] if prompt else "",
            stream_handler is not None,
        )
        model_name = self._config.model_name or "litert-lm"
        image_bytes = base64.b64decode(image_base64)
        msg = Message(
            role="user",
            parts=(
                Part(type="text", text=prompt),
                Part(type="image", image=image_bytes),
            ),
        )
        text = self._generate_text(
            [msg], stream_handler=stream_handler,
        )
        return SummaryResponse(
            text=text,
            model=model_name,
            provider=self.provider_name(),
        )

    def _generate_internal(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> SummaryResponse:
        """Run generation and return a SummaryResponse (used by summarize)."""
        log.debug(
            "_generate_internal: messages=%d, tools=%s, streaming=%s",
            len(messages), bool(tools), stream_handler is not None,
        )
        model_name = self._config.model_name or "litert-lm"
        text = self._generate_text(
            messages, tools=tools, stream_handler=stream_handler,
        )
        return SummaryResponse(
            text=text,
            model=model_name,
            provider=self.provider_name(),
        )

    def _generate_chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> LLMResponse:
        """Run generation and return an LLMResponse (used by generate)."""
        log.debug(
            "_generate_chat: messages=%d, tools=%s, streaming=%s",
            len(messages), bool(tools), stream_handler is not None,
        )
        model_name = self._config.model_name or "litert-lm"
        text = self._generate_text(
            messages, tools=tools, stream_handler=stream_handler,
        )
        return LLMResponse(
            text=text,
            model=model_name,
        )


# ── Tool adapter ───────────────────────────────────────────────────


class _LiteRTToolAdapter:
    """Wraps a canonical ``Tool`` as a litert-lm ``interfaces.Tool``.

    The litert-lm engine uses ``get_tool_description()`` to advertise
    available tools and ``execute()`` for automatic tool calling.
    We advertise the tool but keep execution a no-op (the service layer
    ``ProviderLLMService`` handles the actual tool call loop).
    """

    def __init__(self, tool: Tool) -> None:
        self._tool = tool

    def get_tool_description(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self._tool.name,
                "description": self._tool.description,
                "parameters": {
                    "type": "object",
                    "properties": dict(self._tool.parameters),
                    "required": list(self._tool.required),
                },
            },
        }

    def execute(self, params: Mapping[str, Any]) -> Any:
        # The service layer ToolExecutor runs tools, not here.
        return params


# ── Module-level helpers ───────────────────────────────────────────


def _text_capabilities() -> tuple[str, ...]:
    """Capabilities for text-only models."""
    return (
        "completion", "chat", "streaming",
        "text_input", "text_output",
    )


def _vision_capabilities() -> tuple[str, ...]:
    """Capabilities for vision-capable models."""
    return (
        "completion", "chat", "streaming",
        "text_input", "text_output",
        "image_input", "vision",
    )


def _is_vision_model(model_name: str | None) -> bool:
    """Return ``True`` if *model_name* refers to a vision-capable model."""
    if not model_name:
        return False
    known = lookup_model(model_name)
    return known is not None and known.vision


def _model_def_to_info(model: LiteRTModelDef) -> ProviderModelInfo:
    """Convert a model definition to ``ProviderModelInfo``."""
    capabilities = _vision_capabilities() if model.vision else _text_capabilities()
    return ProviderModelInfo(
        id=model.model_id,
        provider="litert-lm",
        display_name=model.display_name,
        description=model.description,
        capabilities=capabilities,
        sampling_defaults=SamplingDefaults(),
    )
