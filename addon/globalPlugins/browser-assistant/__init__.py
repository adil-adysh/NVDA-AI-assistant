# -*- coding: utf-8 -*-
# URL Announcer + Bookmark System

import globalPluginHandler
import api
import ui
import controlTypes
import extensionPoints
import re
from urllib.parse import urlparse
import threading
import json
import os
import time

DATA_FILE = os.path.join(os.path.dirname(__file__), "bookmarks.json")
DEFAULT_COLLECTION = "default"
MAX_RECENT_ANNOUNCE = 5

FRIENDLY_NAMES = {
    "youtube.com": "YouTube",
    "github.com": "GitHub",
    "google.com": "Google",
}

URL_PATTERN = re.compile(r"https?://[^\s\]\[\)\(\"'<>]+", re.IGNORECASE)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Smart Browser Tools"

    def __init__(self):
        super().__init__()

        self.lastUrl = None
        self.lastDomain = None
        self.timer = None
        self.enabled = True
        self._lock = threading.RLock()
        self._originalSetFocusObject = None
        self._ownsURLProvider = False
        self._ownsSetFocusPatch = False
        self._currentURL = None

        self.data = self._defaultData()
        self.loadData()

        self._initializeURLHooks()

    def terminate(self):
        self.saveData()
        if hasattr(api, "postFocusOrURLChange"):
            try:
                api.postFocusOrURLChange.unregister(self.onURLChange)
            except Exception:
                pass

        if self._ownsSetFocusPatch and self._originalSetFocusObject is not None:
            try:
                current = getattr(api, "setFocusObject", None)
                currentName = str(getattr(current, "__name__", ""))
                currentSelf = getattr(current, "__self__", None)
                if currentName == "_browserAssistantSetFocusObjectHook" and currentSelf is self:
                    api.setFocusObject = self._originalSetFocusObject
            except Exception:
                pass

        super().terminate()

    def _initializeURLHooks(self):
        getCurrentURLFn = getattr(api, "getCurrentURL", None)
        action = getattr(api, "postFocusOrURLChange", None)

        hasProvider = callable(getCurrentURLFn) and action is not None

        if not hasProvider:
            self._ownsURLProvider = True
            self._installURLProviderHooks()

        if hasattr(api, "postFocusOrURLChange"):
            api.postFocusOrURLChange.register(self.onURLChange)

        if self._ownsURLProvider:
            self._patchSetFocusObjectForURLUpdates()
            self._updateURLIfChanged()

    def _installURLProviderHooks(self):
        def browserAssistantGetCurrentURL():
            return self._currentURL

        api.getCurrentURL = browserAssistantGetCurrentURL
        api.postFocusOrURLChange = extensionPoints.Action()

    def _patchSetFocusObjectForURLUpdates(self):
        original = getattr(api, "setFocusObject", None)
        if not callable(original):
            return

        ownerModule = str(getattr(original, "__module__", ""))
        ownerName = str(getattr(original, "__name__", ""))

        # Do not replace BrowserNav or an existing browser-assistant hook.
        if "browserNav" in ownerModule or ownerName == "bnSetFocusObject":
            return
        if ownerName == "_browserAssistantSetFocusObjectHook":
            return

        self._originalSetFocusObject = original
        api.setFocusObject = self._browserAssistantSetFocusObjectHook
        self._ownsSetFocusPatch = True

    def _browserAssistantSetFocusObjectHook(self, obj):
        result = self._originalSetFocusObject(obj)
        self._updateURLIfChanged()
        return result

    def _updateURLIfChanged(self):
        newURL = self._getFocusedURLFromIA2Document()
        if not newURL:
            try:
                focus = api.getFocusObject()
            except Exception:
                focus = None
            newURL = self._extractURLFromObject(focus)

        oldURL = self._currentURL
        self._currentURL = newURL

        if oldURL != newURL and hasattr(api, "postFocusOrURLChange"):
            try:
                api.postFocusOrURLChange.notify()
            except Exception:
                pass

    # ----------------------------
    # URL ANNOUNCER
    # ----------------------------

    def onURLChange(self):
        if self.timer:
            self.timer.cancel()

        self.timer = threading.Timer(0.5, self.processURL)
        self.timer.start()

    # Fallback path when BrowserNav URL hook is not available.
    def event_gainFocus(self, obj, nextHandler):
        nextHandler()
        if self._ownsURLProvider:
            self._updateURLIfChanged()
        self.onURLChange()

    # Extra fallback for app-level focus moves where gainFocus might not fire on the document object.
    def event_foreground(self, obj, nextHandler):
        nextHandler()
        if self._ownsURLProvider:
            self._updateURLIfChanged()
        self.onURLChange()

    def processURL(self):
        if not self.enabled:
            return

        url = self.getURL()
        if not url or url == self.lastUrl:
            return

        self.lastUrl = url
        domain = self.getDomain(url)

        if domain and domain != self.lastDomain:
            self.lastDomain = domain
            ui.message(FRIENDLY_NAMES.get(domain, domain))

    # ----------------------------
    # BOOKMARK SYSTEM
    # ----------------------------

    def _defaultData(self):
        return {
            "schemaVersion": 1,
            "collections": {DEFAULT_COLLECTION: []},
            "currentCollection": DEFAULT_COLLECTION,
        }

    def _normalizeData(self, data):
        if not isinstance(data, dict):
            return self._defaultData()

        collections = data.get("collections")
        if not isinstance(collections, dict):
            collections = {}

        normalizedCollections = {}
        for name, items in collections.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(items, list):
                items = []

            normalizedItems = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str) or not url.strip():
                    continue

                domain = item.get("domain")
                if not isinstance(domain, str) or not domain:
                    domain = self.getDomain(url) or "unknown"

                createdAt = item.get("createdAt", item.get("time", int(time.time())))
                if not isinstance(createdAt, int):
                    createdAt = int(time.time())

                normalizedItems.append(
                    {"url": url.strip(), "domain": domain, "createdAt": createdAt}
                )

            normalizedCollections[name.strip().lower()] = normalizedItems

        if not normalizedCollections:
            normalizedCollections = {DEFAULT_COLLECTION: []}

        currentCollection = str(data.get("currentCollection", DEFAULT_COLLECTION)).strip().lower()
        if currentCollection not in normalizedCollections:
            currentCollection = sorted(normalizedCollections.keys())[0]

        return {
            "schemaVersion": 1,
            "collections": normalizedCollections,
            "currentCollection": currentCollection,
        }

    def _currentCollectionName(self):
        current = self.data.get("currentCollection", DEFAULT_COLLECTION)
        if current not in self.data["collections"]:
            current = sorted(self.data["collections"].keys())[0]
            self.data["currentCollection"] = current
        return current

    def _collectionForCurrent(self):
        name = self._currentCollectionName()
        bookmarks = self.data["collections"].setdefault(name, [])
        return name, bookmarks

    def _findBookmarkByUrl(self, bookmarks, url):
        normalized = url.strip().lower()
        for bookmark in bookmarks:
            if bookmark.get("url", "").strip().lower() == normalized:
                return bookmark
        return None

    def addBookmark(self):
        url = self.getURL()
        if not url:
            ui.message("No URL")
            return

        domain = self.getDomain(url) or "unknown"

        with self._lock:
            collectionName, bookmarks = self._collectionForCurrent()
            if self._findBookmarkByUrl(bookmarks, url):
                ui.message("Already bookmarked")
                return

            bookmarks.append(
                {"url": url.strip(), "domain": domain, "createdAt": int(time.time())}
            )
            self.saveData()

        ui.message(f"Bookmarked in {collectionName}")

    def listBookmarks(self):
        with self._lock:
            collectionName, bookmarks = self._collectionForCurrent()

        if not bookmarks:
            ui.message("Empty collection")
            return

        recent = bookmarks[-MAX_RECENT_ANNOUNCE:]
        labels = [(b.get("domain") or "unknown") for b in recent]
        ui.message(f"{collectionName}: " + ", ".join(labels))

    def switchCollection(self):
        with self._lock:
            names = sorted(self.data["collections"].keys())
            if not names:
                self.data = self._defaultData()
                names = [DEFAULT_COLLECTION]

            current = self.data.get("currentCollection", names[0])
            if current not in names:
                current = names[0]

            nextIndex = (names.index(current) + 1) % len(names)
            newCollection = names[nextIndex]
            self.data["currentCollection"] = newCollection
            self.saveData()

        ui.message(f"Collection: {newCollection}")

    def createCollection(self, name):
        normalized = (name or "").strip().lower()
        if not normalized:
            ui.message("Invalid collection name")
            return

        with self._lock:
            if normalized not in self.data["collections"]:
                self.data["collections"][normalized] = []
            self.data["currentCollection"] = normalized
            self.saveData()

        ui.message(f"Collection: {normalized}")

    def createCollectionFromCurrentDomain(self):
        url = self.getURL()
        if not url:
            ui.message("No URL")
            return

        domain = self.getDomain(url)
        if not domain:
            ui.message("No domain")
            return

        self.createCollection(domain)

    def listCollections(self):
        with self._lock:
            names = sorted(self.data["collections"].keys())
            current = self._currentCollectionName()

        if not names:
            ui.message("No collections")
            return

        labels = [f"{name}*" if name == current else name for name in names]
        ui.message("Collections: " + ", ".join(labels))

    # ----------------------------
    # STORAGE
    # ----------------------------

    def saveData(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as fileHandle:
                json.dump(self.data, fileHandle, indent=2)
        except Exception:
            pass

    def loadData(self):
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as fileHandle:
                    loaded = json.load(fileHandle)
                self.data = self._normalizeData(loaded)
            else:
                self.data = self._defaultData()
        except Exception:
            self.data = self._defaultData()

    # ----------------------------
    # HELPERS
    # ----------------------------

    def getURL(self):
        # Prefer BrowserNav URL provider when available.
        try:
            if hasattr(api, "getCurrentURL"):
                url = api.getCurrentURL()
                if isinstance(url, str) and url.strip():
                    return url.strip()
        except Exception:
            pass

        if self._ownsURLProvider:
            self._updateURLIfChanged()
            if isinstance(self._currentURL, str) and self._currentURL.strip():
                return self._currentURL.strip()

        # BrowserNav-inspired fallback: read IA2 document value.
        url = self._getFocusedURLFromIA2Document()
        if url:
            return url

        candidates = []
        try:
            candidates.append(api.getFocusObject())
        except Exception:
            pass
        try:
            candidates.append(api.getForegroundObject())
        except Exception:
            pass
        try:
            candidates.append(api.getNavigatorObject())
        except Exception:
            pass

        for obj in candidates:
            url = self._extractURLFromObject(obj)
            if url:
                return url

        return None

    def _getFocusedURLFromIA2Document(self):
        document = self._getIA2DocumentFromFocus()
        if document is None:
            return None

        try:
            ia2 = getattr(document, "IAccessibleObject", None)
            if ia2 is None:
                return None
            value = ia2.accValue(0)
            return self._extractURLFromText(value)
        except Exception:
            return None

    def _isDocumentRole(self, role):
        try:
            if role == controlTypes.Role.DOCUMENT:
                return True
        except Exception:
            pass

        # Compatible with multiple NVDA versions where role repr/enum can differ.
        roleText = str(role).upper()
        return "DOCUMENT" in roleText

    def _getIA2DocumentFromFocus(self):
        try:
            focus = api.getFocusObject()
        except Exception:
            focus = None

        if focus is None:
            return None

        try:
            ancestors = list(api.getFocusAncestors())
        except Exception:
            ancestors = []

        for obj in ancestors + [focus]:
            try:
                role = getattr(obj, "role", None)
                if self._isDocumentRole(role):
                    return obj
            except Exception:
                continue

        # Last chance: check treeInterceptor root object.
        try:
            interceptor = getattr(focus, "treeInterceptor", None)
            if interceptor is not None:
                root = getattr(interceptor, "rootNVDAObject", None)
                if root is not None and self._isDocumentRole(getattr(root, "role", None)):
                    return root
        except Exception:
            pass

        return None

    def _extractURLFromObject(self, obj):
        if obj is None:
            return None

        visited = set()
        queue = [obj]

        # Scan a small local graph (object, ancestors, root object) for URL-like text.
        while queue:
            current = queue.pop(0)
            if current is None:
                continue

            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)

            url = self._extractURLFromValues(current)
            if url:
                return url

            try:
                parent = getattr(current, "parent", None)
                if parent is not None:
                    queue.append(parent)
            except Exception:
                pass

            try:
                ti = getattr(current, "treeInterceptor", None)
                if ti is not None:
                    root = getattr(ti, "rootNVDAObject", None)
                    if root is not None:
                        queue.append(root)
            except Exception:
                pass

        return None

    def _extractURLFromValues(self, obj):
        probes = ["value", "name", "description", "displayText", "URL", "url"]
        for attr in probes:
            try:
                value = getattr(obj, attr, None)
            except Exception:
                value = None

            url = self._extractURLFromText(value)
            if url:
                return url

        return None

    def _extractURLFromText(self, value):
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        match = URL_PATTERN.search(text)
        if match:
            return match.group(0)

        if text.startswith("www."):
            return "https://" + text

        parsed = urlparse(text)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return text

        return None

    def getDomain(self, url):
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            return re.sub(r"^www\.", "", domain)
        except Exception:
            return None

    # ----------------------------
    # SCRIPTS (KEYBINDS)
    # ----------------------------

    def script_toggleAnnouncer(self, gesture):
        self.enabled = not self.enabled
        ui.message("Announcer " + ("on" if self.enabled else "off"))

    def script_addBookmark(self, gesture):
        self.addBookmark()

    def script_listBookmarks(self, gesture):
        self.listBookmarks()

    def script_switchCollection(self, gesture):
        self.switchCollection()

    def script_createDomainCollection(self, gesture):
        self.createCollectionFromCurrentDomain()

    def script_listCollections(self, gesture):
        self.listCollections()

    def script_announceURL(self, gesture):
        url = self.getURL()
        if url:
            ui.message(url)
        else:
            ui.message("No URL")

    __gestures = {
        "kb:NVDA+Shift+A": "toggleAnnouncer",
        "kb:NVDA+Shift+B": "addBookmark",
        "kb:NVDA+Shift+L": "listBookmarks",
        "kb:NVDA+Shift+C": "switchCollection",
        "kb:NVDA+Shift+G": "createDomainCollection",
        "kb:NVDA+Shift+J": "listCollections",
        "kb:NVDA+Shift+U": "announceURL",
    }
