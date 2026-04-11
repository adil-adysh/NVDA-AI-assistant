# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context import PromptContext, PageContext, ImageContext
from .context_collectors import ImageContextCollector, PageContextCollector
from .context_pipeline import ContextPipeline
from .chat_coordinator import ChatCoordinator
from .llm_service import LLMService
from .prompt_builders import build_image_description_prompt, build_page_summary_prompt
from .request_metrics import estimate_tokens
from .models import ProgressEvent, ProgressHandler


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
    id: str
    description: str
    context_profile: tuple[str, ...]
    prompt_key: str
    tools: tuple[str, ...] = ()
    requires_input: bool = False


@dataclass(frozen=True, slots=True)
class UseCaseResult:
    success: bool
    message: str | None = None
    prompt_context: PromptContext | None = None
    initial_text: str | None = None
    initial_image_base64: str | None = None
    metadata: dict[str, Any] | None = None


class UseCaseEngine:
    def __init__(
        self,
        chat_coordinator: ChatCoordinator,
        llm_service: LLMService,
        context_pipeline: ContextPipeline | None = None,
        page_context_collector: PageContextCollector | None = None,
        image_context_collector: ImageContextCollector | None = None,
    ) -> None:
        self._chat_coordinator = chat_coordinator
        self._llm_service = llm_service
        self._context_pipeline = context_pipeline
        self._page_context_collector = page_context_collector
        self._image_context_collector = image_context_collector
        self._specs = {spec.id: spec for spec in self._default_use_cases()}
        self._handlers = {
            "summary": self.summarize_current_page,
            "describe_image": self.describe_current_window,
            "open_chat": self.prepare_chat,
            "open_chat_with_page_content": self.prepare_chat_with_page_content,
            "open_chat_with_screenshot": self.prepare_chat_with_screenshot,
        }

    @staticmethod
    def _default_use_cases() -> tuple[UseCaseSpec, ...]:
        return (
            UseCaseSpec(
                id="summary",
                description="Summarize the current page content.",
                context_profile=("app", "accessibility"),
                prompt_key="page_summary",
                tools=(),
                requires_input=False,
            ),
            UseCaseSpec(
                id="describe_image",
                description="Describe the current foreground window screenshot.",
                context_profile=("image",),
                prompt_key="image_description",
                tools=(),
                requires_input=False,
            ),
            UseCaseSpec(
                id="open_chat",
                description="Open a blank chat session.",
                context_profile=(),
                prompt_key="chat",
                tools=(),
                requires_input=False,
            ),
            UseCaseSpec(
                id="open_chat_with_page_content",
                description="Open chat with the current page content preloaded.",
                context_profile=("app", "accessibility"),
                prompt_key="chat_with_page_context",
                tools=(),
                requires_input=True,
            ),
            UseCaseSpec(
                id="open_chat_with_screenshot",
                description="Open chat with a screenshot attached.",
                context_profile=("image",),
                prompt_key="chat_with_image_context",
                tools=(),
                requires_input=True,
            ),
        )

    def get_spec(self, use_case_id: str) -> UseCaseSpec:
        try:
            return self._specs[use_case_id]
        except KeyError as error:
            raise ValueError(f"Unknown use case: {use_case_id}") from error

    def execute(self, use_case_id: str, progress: ProgressHandler | None = None, **kwargs: Any) -> UseCaseResult:
        def emit(stage: str, message: str) -> None:
            if progress is not None:
                progress(ProgressEvent(stage=stage, message=message))

        emit("start", f"Starting {use_case_id}")
        try:
            handler = self._handlers.get(use_case_id)
            if handler is None:
                raise ValueError(f"Unknown use case: {use_case_id}")
            result = handler(emit=emit, **kwargs)
        except Exception as error:
            emit("error", str(error))
            raise

        emit("complete", result.message or f"{use_case_id} complete")
        return result

    def _collect_prompt_context(self, use_case_id: str, **kwargs: Any) -> PromptContext | None:
        if self._context_pipeline is None:
            return None
        spec = self.get_spec(use_case_id)
        return self._context_pipeline.collect(use_case_id=use_case_id, context_profile=spec.context_profile, **kwargs)

    def _collect_page_context(self) -> PageContext:
        if self._page_context_collector is not None:
            fragment = self._page_context_collector.collect("summary")
            page_context = fragment.facts.get("page_context")
            if isinstance(page_context, PageContext):
                return page_context
        raise ValueError("Unable to collect page context")

    def _collect_image_context(self) -> ImageContext:
        if self._image_context_collector is not None:
            fragment = self._image_context_collector.collect("describe_image")
            image_context = fragment.facts.get("image_context")
            if isinstance(image_context, ImageContext):
                return image_context
        raise ValueError("Unable to collect image context")

    def summarize_current_page(self, emit: Any | None = None) -> UseCaseResult:
        if emit is not None:
            emit("collecting_context", "Collecting page content...")
        page_context = self._collect_page_context()
        if emit is not None:
            emit("building_prompt", "Building summary prompt...")
        prompt = build_page_summary_prompt(page_context)
        if emit is not None:
            emit("llm_request", "Generating summary...")
        response = self._llm_service.summarize(prompt)
        return UseCaseResult(
            success=True,
            message="Summary ready",
            initial_text=page_context.text,
            prompt_context=PromptContext(
                use_case_id="summary",
                facts={"page_context": page_context},
                text=page_context.text,
                metadata={
                    "prompt_key": "page_summary",
                    "prompt_chars": len(prompt),
                    "prompt_tokens_estimated": estimate_tokens(prompt),
                },
            ),
            metadata={"output_text": response.text, "model": response.model, "prompt_key": "page_summary"},
        )

    def describe_current_window(self, emit: Any | None = None) -> UseCaseResult:
        if emit is not None:
            emit("collecting_context", "Collecting screenshot context...")
        image_context = self._collect_image_context()
        if emit is not None:
            emit("building_prompt", "Building image description prompt...")
        prompt = build_image_description_prompt(image_context)
        if emit is not None:
            emit("llm_request", "Generating image description...")
        response = self._llm_service.describe_image(
            image_base64=image_context.image_base64 or "",
            prompt=prompt,
        )
        return UseCaseResult(
            success=True,
            message="Image description ready",
            initial_image_base64=image_context.image_base64,
            prompt_context=PromptContext(
                use_case_id="describe_image",
                facts={"image_context": image_context},
                image_base64=image_context.image_base64,
                metadata={
                    "prompt_key": "image_description",
                    "prompt_chars": len(prompt),
                    "prompt_tokens_estimated": estimate_tokens(prompt),
                },
            ),
            metadata={"output_text": response.text, "model": response.model, "prompt_key": "image_description"},
        )

    def prepare_chat(
        self,
        initial_text: str | None = None,
        initial_image_base64: str | None = None,
        emit: Any | None = None,
    ) -> UseCaseResult:
        return UseCaseResult(
            success=True,
            initial_text=initial_text,
            initial_image_base64=initial_image_base64,
            message="Chat window ready",
            prompt_context=PromptContext(
                use_case_id="open_chat",
                facts={},
                text=initial_text,
                image_base64=initial_image_base64,
                metadata={"prompt_key": "chat"},
            ),
        )

    def prepare_chat_with_page_content(self, page_content: str | None = None, emit: Any | None = None) -> UseCaseResult:
        if emit is not None:
            emit("collecting_context", "Collecting page content...")
        prompt_context = self._collect_prompt_context("open_chat_with_page_content")
        if emit is not None:
            emit("building_prompt", "Building chat prompt...")
        page_context = None
        if prompt_context is not None:
            page_context = prompt_context.facts.get("page_context")

        if isinstance(page_context, PageContext):
            title = page_context.title or "Unknown"
            app_title = page_context.app_title or "Unknown"
            page_content = (
                "Page content:\n"
                f"Title: {title}\n"
                f"App: {app_title}\n\n"
                f"{page_context.text}\n\n"
                "Question: "
            )
        elif not page_content and prompt_context is not None:
            page_content = prompt_context.text or ""

        return UseCaseResult(
            success=True,
            initial_text=page_content,
            message="Chat window ready",
            prompt_context=prompt_context,
            metadata={"prompt_key": "chat_with_page_context"},
        )

    def prepare_chat_with_screenshot(self, initial_text: str | None = None, image_base64: str | None = None, emit: Any | None = None) -> UseCaseResult:
        if emit is not None:
            emit("collecting_context", "Collecting screenshot context...")
        prompt_context = self._collect_prompt_context("open_chat_with_screenshot")
        if emit is not None:
            emit("building_prompt", "Building chat prompt...")
        if prompt_context is not None:
            image_base64 = prompt_context.image_base64 or image_base64
            if not initial_text:
                initial_text = "Describe this screenshot."

        return UseCaseResult(
            success=True,
            initial_text=initial_text,
            initial_image_base64=image_base64,
            message="Chat window ready",
            prompt_context=prompt_context,
            metadata={"prompt_key": "chat_with_image_context"},
        )
