# -*- coding: utf-8 -*-
# URL Announcer NVDA Addon (Prototype)

import globalPluginHandler
import api
import ui
import extensionPoints
import re
from urllib.parse import urlparse

class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    scriptCategory = "URL Announcer"

    def __init__(self):
        super(GlobalPlugin, self).__init__()

        self.lastUrl = None

        # Register to URL change event (from BrowserNav or similar addons)
        if hasattr(api, "postFocusOrURLChange"):
            api.postFocusOrURLChange.register(self.onURLChange)
        else:
            ui.message("URL event system not available")

    def terminate(self):
        # Clean unregister
        if hasattr(api, "postFocusOrURLChange"):
            try:
                api.postFocusOrURLChange.unregister(self.onURLChange)
            except:
                pass
        super(GlobalPlugin, self).terminate()

    # ----------------------------
    # Core Logic
    # ----------------------------

    def onURLChange(self):
        url = self.getCurrentURLSafe()

        if not url:
            return

        if url == self.lastUrl:
            return

        self.lastUrl = url

        # Choose what to speak
        domain = self.extractDomain(url)

        if domain:
            ui.message(domain)
        else:
            ui.message(url)

    # ----------------------------
    # Helpers
    # ----------------------------

    def getCurrentURLSafe(self):
        try:
            if hasattr(api, "getCurrentURL"):
                return api.getCurrentURL()
        except:
            pass
        return None

    def extractDomain(self, url):
        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # Clean common prefixes
            domain = re.sub(r"^www\.", "", domain)

            return domain
        except:
            return None

    # ----------------------------
    # Manual Trigger (for testing)
    # ----------------------------

    def script_announceURL(self, gesture):
        url = self.getCurrentURLSafe()

        if not url:
            ui.message("No URL")
            return

        domain = self.extractDomain(url)

        if domain:
            ui.message(f"Current site: {domain}")
        else:
            ui.message(url)

    __gestures = {
        "kb:NVDA+Shift+U": "announceURL",
    }
