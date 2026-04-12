# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
from logHandler import log
import threading
import builtins
from collections.abc import Callable
from typing import Any, cast

import addonHandler
import globalPluginHandler
import gui
import ui
from scriptHandler import script

from .image_services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from .metrics_reporter import FileMetricsReporter
from .service import ChatCoordinator, ProviderLLMService
from . import nvda_ui
from .settings import get_provider, get_provider_state, set_provider, subscribe_provider_state_change, unsubscribe_provider_state_change
from .providers.interfaces import LLMProviderError
from .tools import ToolDefinition, ToolRegistry, ToolExecutor
from .providers.provider_proxy import ProviderProxy
from .settings_panel import AIAssistantSettingsPanel
from .use_case import UseCaseEngine
from .context import BrowserAwarePageExtractor, ContextPipeline, ImageContextCollector, PageContextCollector
from .core.events import ProgressEvent
from . import addonConfig

def _translate(message: str) -> str:
    return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("Smart Browser Tools")

    def __init__(self) -> None:
        super().__init__()
        self.assistantLayerModeActive = False
        self.layeredScriptToRun = None
        addonHandler.initTranslation()
        addonConfig.initialize()
        log.debug("Browser Assistant plugin initializing")
        self._provider = ProviderProxy()
        self._metrics_reporter = FileMetricsReporter()
        self._pageContextCollector = PageContextCollector(extractor=BrowserAwarePageExtractor())
        self._imageContextCollector = ImageContextCollector(
            capture_service=ImageCaptureService(),
            preprocessor=ImagePreprocessor(),
            encoder=ImageEncoder(),
        )

        self._contextPipeline = ContextPipeline(
            collectors=(self._pageContextCollector, self._imageContextCollector),
        )
        self._toolRegistry = ToolRegistry()
        self._register_default_tools()
        self._toolExecutor = ToolExecutor(self._toolRegistry)
        self._llmService = ProviderLLMService(self._provider, tool_executor=self._toolExecutor)
        self._chatCoordinator = ChatCoordinator(
            client=self._llmService,
            tool_executor=self._toolExecutor,
            metrics_reporter=self._metrics_reporter,
        )
        self._useCaseEngine = UseCaseEngine(
            chat_coordinator=self._chatCoordinator,
            llm_service=self._llmService,
            context_pipeline=self._contextPipeline,
            page_context_collector=self._pageContextCollector,
            image_context_collector=self._imageContextCollector,
        )
        subscribe_provider_state_change(self._on_provider_state_change)
        self._assistantLayerGestures = (
            ("s", self.script_summarizeCurrentPage),
            ("i", self.script_describeCurrentWindow),
            ("c", self.script_openChatWindow),
            ("p", self.script_openChatWithPageContent),
            ("x", self.script_openChatWithScreenshot),
            ("t", self.script_toggleAIProvider),
            ("h", self.script_assistantLayerHelp),
        )
        self._startModelPreload()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(AIAssistantSettingsPanel)
        log.debug("Browser Assistant plugin initialized")

    def _register_default_tools(self) -> None:
        self._toolRegistry.register_tool(
            ToolDefinition(
                name="get_time",
                description="Get the current local date and time.",
                parameters={},
                required=[],
                executor=lambda args: __import__("datetime").datetime.now().isoformat(),
            )
        )

    def _startModelPreload(self):
        def worker():
            provider_name = self._llmService.provider_name()
            ui.message(f"Checking {provider_name} model availability.")

            try:
                model = self._llmService.ensure_model_available(on_progress=ui.message)
            except LLMProviderError as error:
                ui.message(str(error))
            except Exception as error:
                log.exception("Unexpected error during model preload")
                ui.message(str(error))
            else:
                ui.message(f"{provider_name.capitalize()} model {model} is ready.")

        thread = threading.Thread(
            target=worker,
            name="BrowserAssistantModelPreload",
            daemon=True,
        )
        thread.start()

    def _on_provider_state_change(self, provider_state: Any) -> None:
        try:
            from . import chat_ui

            if chat_ui.chatDialogInstance:
                chat_ui.chatDialogInstance.update_provider_state(provider_state)
        except Exception:
            log.exception("Error updating chat dialog title after provider state changed")

    # ------------------------------------------------------------------
    # Scripts (keybinds)
    # ------------------------------------------------------------------

    @script(
        description=_("Summarizes the current page using the selected AI provider."),
    )
    def script_summarizeCurrentPage(self, gesture: Any):
        log.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
        self._run_use_case_in_background(
            "summary",
            title=_("Page summary"),
            render_result=lambda result: self._present_use_case_result(result, title=_("Page summary")),
        )

    def terminate(self) -> None:
        try:
            unsubscribe_provider_state_change(self._on_provider_state_change)
        except Exception:
            log.exception("Error unsubscribing provider state listener")
        try:
            self._llmService.close()
        except Exception:
            log.exception("Error closing provider during terminate")
        super().terminate()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(AIAssistantSettingsPanel)

    @script(
        description=_("Captures and describes the current foreground window using the selected AI provider."),
    )
    def script_describeCurrentWindow(self, gesture: Any):
        log.debug("Script describeCurrentWindow invoked gesture=%s", gesture)
        self._run_use_case_in_background(
            "describe_image",
            title=_("Image description"),
            render_result=lambda result: self._present_use_case_result(result, title=_("Image description")),
        )

    @script(
        description=_("Opens the AI chat window."),
    )
    def script_openChatWindow(self, gesture: Any):
        log.debug("Script openChatWindow invoked gesture=%s", gesture)
        self._run_use_case_in_background(
            "open_chat",
            title=_("AI Chat"),
            render_result=lambda result: self._open_chat_window(
                initial_text=result.initial_text,
                initial_image_base64=result.initial_image_base64,
            ),
        )

    def _open_chat_window(
        self,
        initial_text: str | None = None,
        initial_image_base64: str | None = None,
    ) -> None:
        from . import chat_ui

        if chat_ui.chatDialogInstance:
            try:
                chat_ui.chatDialogInstance.update_provider_state(get_provider_state())
                chat_ui.chatDialogInstance.Raise()
                chat_ui.chatDialogInstance.set_initial_state(initial_text, initial_image_base64)
            except Exception:
                pass
            return

        gui.mainFrame.prePopup()
        parent = getattr(gui, "mainFrame", None)
        chat_ui.chatDialogInstance = chat_ui.ChatDialog(
            parent,
            coordinator=self._chatCoordinator,
            tool_registry=self._toolRegistry,
            provider_state=get_provider_state(),
            initial_text=initial_text,
            initial_image_base64=initial_image_base64,
        )
        try:
            chat_ui.chatDialogInstance.Show()
        except Exception:
            chat_ui.chatDialogInstance = None
            raise
        finally:
            gui.mainFrame.postPopup()

    def _run_use_case_in_background(self, use_case_id: str, title: str, render_result: Callable[[Any], None]) -> None:
        def worker() -> None:
            try:
                result = self._useCaseEngine.execute(use_case_id, progress=self._progress_handler)
            except Exception as error:
                nvda_ui.queue(ui.message, _(f"Error: {error}"))
                return

            nvda_ui.queue(render_result, result)

        thread = threading.Thread(
            target=worker,
            name=f"AIassistant{title.replace(' ', '')}Worker",
            daemon=True,
        )
        thread.start()

    def _present_use_case_result(self, use_case_result: Any, title: str) -> None:
        output_text = None
        if isinstance(use_case_result, dict):
            output_text = use_case_result.get("output_text")
        else:
            metadata = getattr(use_case_result, "metadata", None)
            if isinstance(metadata, dict):
                output_text = metadata.get("output_text")

        if not isinstance(output_text, str) or not output_text.strip():
            ui.message(_("No result to display."))
            return

        ui.browseableMessage(output_text, title=title)

    def _progress_handler(self, event: ProgressEvent) -> None:
        if event.stage == "error":
            nvda_ui.queue(ui.message, _("Error: ") + event.message)
            return

        if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
            nvda_ui.queue(ui.message, event.message)

    @script(
        description=_("Opens the AI chat window with current page content preloaded."),
    )
    def script_openChatWithPageContent(self, gesture: Any):
        log.debug("Script openChatWithPageContent invoked gesture=%s", gesture)
        self._run_use_case_in_background(
            "open_chat_with_page_content",
            title=_("AI Chat"),
            render_result=lambda result: self._open_chat_window(initial_text=result.initial_text),
        )

    @script(
        description=_("Opens the AI chat window with a screenshot attached."),
    )
    def script_openChatWithScreenshot(self, gesture: Any):
        log.debug("Script openChatWithScreenshot invoked gesture=%s", gesture)
        self._run_use_case_in_background(
            "open_chat_with_screenshot",
            title=_("AI Chat"),
            render_result=lambda result: self._open_chat_window(
                initial_text=result.initial_text,
                initial_image_base64=result.initial_image_base64,
            ),
        )

    @script(
        description=_(
            "Activate the AI assistant command layer. "
            "Press S for summary, I for image describe, C for chat, H for help."
        ),
        gesture="kb:NVDA+Shift+A",
    )
    def script_assistantLayerCommands(self, gesture: Any):
        log.debug("Script assistantLayerCommands invoked gesture=%s", gesture)
        if self.assistantLayerModeActive:
            self.script_error(gesture)
            return
        self.layeredScriptToRun = None
        for gesture_key, handler in self._assistantLayerGestures:
            self.bindGesture(f"kb:{gesture_key}", handler.__name__[7:])
        self.assistantLayerModeActive = True
        ui.message(
            _(
                "AI assistant layer active. Press S for summary, I for image describe, C for chat, P for page content, X for screenshot, T for provider toggle, or H for help."
            )
        )

    def getScript(self, gesture: Any):
        if not getattr(self, "assistantLayerModeActive", False):
            return globalPluginHandler.GlobalPlugin.getScript(self, gesture)
        script = globalPluginHandler.GlobalPlugin.getScript(self, gesture)
        if not script:
            return self.script_error
        self.layeredScriptToRun = next(
            (handler for key, handler in self._assistantLayerGestures if key == gesture.mainKeyName),
            None,
        )
        return self.runAndFinish

    def runAndFinish(self, gesture: Any):
        try:
            if self.layeredScriptToRun is not None:
                self.layeredScriptToRun(gesture)
            else:
                ui.message(_("Can't find this assistant layer script."))
        finally:
            self.finish()

    def finish(self) -> None:
        self.assistantLayerModeActive = False
        self.layeredScriptToRun = None
        self.clearGestureBindings()
        self.bindGestures(self.__gestures)

    def script_error(self, gesture: Any):
        ui.message(_("Can't find this assistant layer script."))
        self.finish()

    @script(
        description=_("Toggles the active AI provider between Ollama and Gemini."),
    )
    def script_toggleAIProvider(self, gesture: Any):
        log.debug("Script toggleAIProvider invoked gesture=%s", gesture)
        current_provider = get_provider()
        target_provider = "gemini" if current_provider == "ollama" else "ollama"
        self._set_active_provider(target_provider)

    def _set_active_provider(self, provider: str) -> None:
        try:
            set_provider(provider)
        except Exception as error:
            ui.message(str(error))
            return

        ui.message(_(f"AI provider switched to {provider.capitalize()}."))
        from . import chat_ui

        if chat_ui.chatDialogInstance:
            try:
                chat_ui.chatDialogInstance.update_provider_state(get_provider_state())
            except Exception:
                log.exception("Error updating chat dialog title after provider switch")

        self._startModelPreload()

    @script(
        description=_("Lists available AI assistant layer commands."),
    )
    def script_assistantLayerHelp(self, gesture: Any):
        ui.message(
            _(
                "Assistant layer commands: S for summary, I for image describe, C for chat, P for page content, X for screenshot, T for provider toggle, H for help. Press the key after activating the layer with NVDA+Shift+A."
            )
        )
