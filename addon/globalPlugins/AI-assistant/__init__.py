# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
import logging
import threading
from typing import Any

import addonHandler
import globalPluginHandler
import gui
import ui
from scriptHandler import script

from .browser_extractor import BrowserAwarePageExtractor
from .download_progress import DownloadProgressTracker
from .image_description import ImageDescriptionCoordinator
from .image_services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from .metrics_reporter import FileMetricsReporter
from .page_summary import PageSummaryCoordinator
from .providers.base import LLMProviderError
from .providers.provider_proxy import ProviderProxy
from .settings_panel import AIAssistantSettingsPanel
from .chat_coordinator import ChatCoordinator

logger = logging.getLogger(__name__)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("Smart Browser Tools")
    assistantLayerModeActive = False
    layeredScriptToRun = None

    def __init__(self):
        super().__init__()
        addonHandler.initTranslation()
        logger.debug("Browser Assistant plugin initializing")
        self._provider = ProviderProxy()
        self._metrics_reporter = FileMetricsReporter()
        self._capture_service = ImageCaptureService()
        self._preprocessor = ImagePreprocessor()
        self._encoder = ImageEncoder()

        self._pageSummary = PageSummaryCoordinator(
            extractor=BrowserAwarePageExtractor(),
            client=self._provider,
            metrics_reporter=self._metrics_reporter,
        )
        self._imageDescription = ImageDescriptionCoordinator(
            client=self._provider,
            metrics_reporter=self._metrics_reporter,
            capture_service=self._capture_service,
            preprocessor=self._preprocessor,
            encoder=self._encoder,
        )
        self._chatCoordinator = ChatCoordinator(
            client=self._provider,
            metrics_reporter=self._metrics_reporter,
        )
        self._assistantLayerGestures = (
            ("s", self.script_summarizeCurrentPage),
            ("i", self.script_describeCurrentWindow),
            ("c", self.script_openChatWindow),
            ("h", self.script_assistantLayerHelp),
        )
        self._startModelPreload()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(AIAssistantSettingsPanel)
        logger.debug("Browser Assistant plugin initialized")

    def _startModelPreload(self):
        def worker():
            provider_name = self._provider.provider_name()
            ui.message(f"Checking {provider_name} model availability.")
            announcer = DownloadProgressTracker(ui.message)

            try:
                model = self._provider.ensure_model_available(on_progress=announcer.process_event)
            except LLMProviderError as error:
                ui.message(str(error))
            else:
                ui.message(f"{provider_name.capitalize()} model {model} is ready.")

        thread = threading.Thread(
            target=worker,
            name="BrowserAssistantModelPreload",
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Scripts (keybinds)
    # ------------------------------------------------------------------

    @script(
        description=_("Summarizes the current page using the selected AI provider."),
        gesture="kb:NVDA+Shift+S",
    )
    def script_summarizeCurrentPage(self, gesture: Any):
        logger.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
        self._pageSummary.summarizeCurrentPage()

    def terminate(self):
        try:
            self._provider.close()
        except Exception:
            logger.exception("Error closing provider during terminate")
        super().terminate()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(AIAssistantSettingsPanel)

    @script(
        description=_("Captures and describes the current foreground window using the selected AI provider."),
        gesture="kb:NVDA+Shift+I",
    )
    def script_describeCurrentWindow(self, gesture: Any):
        logger.debug("Script describeCurrentWindow invoked gesture=%s", gesture)
        self._imageDescription.describeCurrentWindow()

    @script(
        description=_("Opens the AI chat window."),
        gesture="kb:NVDA+Shift+C",
    )
    def script_openChatWindow(self, gesture: Any):
        logger.debug("Script openChatWindow invoked gesture=%s", gesture)
        from . import chat_ui

        if chat_ui.chatDialogInstance:
            try:
                chat_ui.chatDialogInstance.Raise()
            except Exception:
                pass
            return

        gui.mainFrame.prePopup()
        parent = getattr(gui, "mainFrame", None)
        chat_ui.chatDialogInstance = chat_ui.ChatDialog(parent, coordinator=self._chatCoordinator)
        try:
            chat_ui.chatDialogInstance.Show()
        except Exception:
            chat_ui.chatDialogInstance = None
            raise
        finally:
            gui.mainFrame.postPopup()

    @script(
        description=_(
            "Activate the AI assistant command layer. "
            "Press S for summary, I for image describe, C for chat, H for help."
        ),
        gesture="kb:NVDA+Shift+A",
    )
    def script_assistantLayerCommands(self, gesture: Any):
        logger.debug("Script assistantLayerCommands invoked gesture=%s", gesture)
        if self.assistantLayerModeActive:
            self.script_error(gesture)
            return
        for gesture_key, handler in self._assistantLayerGestures:
            self.bindGesture(f"kb:{gesture_key}", handler.__name__[7:])
        self.assistantLayerModeActive = True
        ui.message(
            _("AI assistant layer active. Press S for summary, I for image describe, C for chat, or H for help.")
        )

    def getScript(self, gesture):
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

    def runAndFinish(self, gesture):
        if self.layeredScriptToRun is not None:
            self.layeredScriptToRun(gesture)
        else:
            ui.message(_("Can't find this assistant layer script."))
        self.finish()

    def finish(self):
        self.assistantLayerModeActive = False
        self.clearGestureBindings()
        self.bindGestures(self.__gestures)

    def script_error(self, gesture):
        ui.message(_("Can't find this assistant layer script."))
        self.finish()

    @script(
        description=_("Lists available AI assistant layer commands."),
    )
    def script_assistantLayerHelp(self, gesture: Any):
        ui.message(
            _(
                "Assistant layer commands: S for summary, I for image describe, C for chat, H for help. "
                "Press the key after activating the layer with NVDA+Shift+A."
            )
        )
