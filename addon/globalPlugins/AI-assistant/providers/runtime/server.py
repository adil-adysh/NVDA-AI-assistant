# -*- coding: utf-8 -*-
"""LiteRT-LM server process supervisor.

Manages the lifecycle of a ``litert-lm serve`` process that exposes an
OpenAI-compatible HTTP API on localhost.  The server runs inside a
self-contained Python 3.13 embeddable runtime that is downloaded
on demand — users do not need Python installed separately.

Usage::

    supervisor = LiteRTServerSupervisor()
    supervisor.install("0.15.0")
    supervisor.start()
    supervisor.wait_until_ready()
    # ... use the provider at http://127.0.0.1:9379 ...
    supervisor.stop()
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from .config import RuntimeConfig
from .download import RuntimeDownloadService
from .paths import get_runtime_path
from ..interfaces import LLMProviderError

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

DEFAULT_LITERT_PORT = 9379
DEFAULT_LITERT_HOST = "127.0.0.1"
DEFAULT_LITERT_VERSION = "0.15.0"
SERVER_READY_POLL_INTERVAL = 0.5  # seconds

# GitHub release URL template for the self-contained runtime ZIP.
_RUNTIME_DOWNLOAD_BASE = (
    "https://github.com/adil-adysh/NVDA-AI-assistant/releases/download/"
    "litert-runtime-v{version}/litert-lm-{version}-windows-x64-runtime.zip"
)

_supervisor: LiteRTServerSupervisor | None = None


def _default_litert_dir() -> Path:
    """Return the add-on-owned LiteRT-LM registry directory.

    LiteRT-LM's CLI defaults to ``%USERPROFILE%/.litert-lm``.  That is a
    process-global location and can be shared with another installation or
    CLI version, so the add-on must give both import and serve the same
    private registry instead.
    """
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "nvda" / "AIAssistant" / "litert-lm"


def get_litert_supervisor() -> LiteRTServerSupervisor:
    """Return the module-level singleton :class:`LiteRTServerSupervisor`.

    Creates the instance on first call with defaults that match the
    add-on configuration.
    """
    global _supervisor
    if _supervisor is None:
        _supervisor = LiteRTServerSupervisor()
    return _supervisor


class LiteRTServerError(LLMProviderError):
    """Raised when the LiteRT-LM server cannot be started or is unhealthy."""


class LiteRTServerSupervisor:
    """Manages the lifecycle of a ``litert-lm serve`` process.

    The server runs inside a self-contained Python 3.13 runtime that is
    downloaded on first use.  No system Python installation is required.
    """

    def __init__(
        self,
        *,
        port: int = DEFAULT_LITERT_PORT,
        host: str = DEFAULT_LITERT_HOST,
        version: str = DEFAULT_LITERT_VERSION,
    ) -> None:
        self._port = port
        self._host = host
        self._version = version
        self._process: subprocess.Popen[str] | None = None
        self._lifecycle_lock = threading.RLock()
        self._download_service = RuntimeDownloadService(
            url_builder=self._build_download_url,
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """The base URL clients should use to reach the server."""
        return f"http://{self._host}:{self._port}"

    @property
    def is_installed(self) -> bool:
        """True when the self-contained runtime has been downloaded and extracted."""
        return self._server_python().exists()

    @property
    def is_running(self) -> bool:
        """True when the server process is alive."""
        return self._process is not None and self._process.poll() is None

    def install(
        self,
        on_progress: Callable[[str], None] | None = None,
        on_bytes_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download and extract the self-contained litert-lm runtime.

        The runtime includes Python 3.13 and litert-lm — no system
        Python or pip is needed.

        Args:
            on_progress: Optional callback receiving status strings.
            on_bytes_progress: Optional callback ``(downloaded_bytes, total_bytes)``
                for byte-level progress during download.

        Returns the path to the runtime directory.

        Raises:
            LiteRTServerError: If the download or extraction fails.
        """
        server_dir = self._server_dir()
        python_exe = self._server_python()

        if python_exe.exists():
            log.debug("LiteRT runtime already present at %s", server_dir)
            return server_dir

        self._report(on_progress, "Downloading LiteRT-LM runtime...")

        try:
            self._download_service.download(
                runtime="litert-lm",
                version=self._version,
                platform="windows-x64",
                on_progress=on_progress,
                on_bytes_progress=on_bytes_progress,
            )
        except Exception as exc:
            raise LiteRTServerError(
                f"Failed to download LiteRT-LM runtime {self._version}: {exc}"
            ) from exc

        if not python_exe.exists():
            raise LiteRTServerError(
                f"Runtime extracted but python.exe not found at {python_exe}"
            )

        log.info("LiteRT runtime installed at %s", server_dir)
        return server_dir

    def start(
        self,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Start the ``litert-lm serve`` process.

        The server starts without a pre-loaded model — the model is loaded
        lazily when the first ``/v1/chat/completions`` request references it.

        Args:
            on_progress: Optional status callback.

        Raises:
            LiteRTServerError: If the runtime is not installed or
                the process fails to start.
        """
        with self._lifecycle_lock:
            if self.is_running:
                log.debug("LiteRT server is already running")
                return

        python_exe = self._server_python()
        if not python_exe.exists():
            raise LiteRTServerError(
                "LiteRT server is not installed. Call install() first."
            )

        self._report(on_progress, f"Starting LiteRT-LM server on port {self._port}...")

        with self._lifecycle_lock:
            if self.is_running:
                return
            try:
                self._litert_dir().mkdir(parents=True, exist_ok=True)
                self._process = subprocess.Popen(
                    [
                        str(python_exe),
                        "-m",
                        "litert_lm_cli.main",
                        "serve",
                        "--host",
                        self._host,
                        "--port",
                        str(self._port),
                    ],
                    # Never leave pipes unread: a verbose server can fill a
                    # pipe and stop servicing chat requests.
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    env=self._process_environment(),
                )
            except Exception as exc:
                raise LiteRTServerError(
                    f"Failed to start LiteRT-LM server: {exc}"
                ) from exc

        log.info(
            "LiteRT server started (pid=%d) on %s",
            self._process.pid,
            self.base_url,
        )

    def stop(self) -> None:
        """Stop the server process gracefully, then forcefully if needed."""
        with self._lifecycle_lock:
            if self._process is None:
                return

            if self._process.poll() is None:
                log.debug("Stopping LiteRT server (pid=%d)...", self._process.pid)
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log.warning("LiteRT server did not stop; killing")
                    self._process.kill()
                    self._process.wait(timeout=5)

        self._process = None
        log.info("LiteRT server stopped")

    def adopt(self) -> None:
        """Acknowledge a server running on our host:port without a process handle.

        After an NVDA restart the process handle is lost but the server may
        still be alive.  Call this when ``is_healthy()`` returns True even
        though ``is_running`` is False so the supervisor treats the server
        as available without trying to start a new one.
        """
        # Nothing to do — the absence of a process handle is the signal.
        # Callers check is_healthy() independently to decide whether the
        # existing server is usable.

    def catalog_model_dir(self, model_id: str) -> Path | None:
        """Return the on-disk catalog directory for *model_id*, if any.

        LiteRT-LM stores imported models under the directory supplied through
        ``LITERT_LM_DIR``.  This is deliberately not the global user home.
        """
        dir_name = model_id.replace("/", "--")
        return self._litert_dir() / "models" / dir_name

    def is_healthy(self, timeout: float = 5.0) -> bool:
        """Check if the server is responding to health checks.

        Sends a GET to ``/v1/models`` — the lightest endpoint.
        Does NOT require ``is_running`` to be True so that the check
        still works after an NVDA restart when the process handle is lost.
        """
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_server_models(self) -> set[str]:
        """Return the set of model IDs currently registered with the server.

        Queries ``/v1/models`` and extracts the ``id`` field from each entry.
        Returns an empty set if the server is not reachable.
        """
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return set()

        if not isinstance(data, dict):
            return set()
        model_list = data.get("data")
        if not isinstance(model_list, list):
            return set()
        return {
            str(m.get("id", "")).strip()
            for m in model_list
            if isinstance(m, dict) and m.get("id")
        }

    def import_model(
        self,
        model_path: str | Path,
        model_id: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Import a local ``.litertlm`` file into the server's model catalog.

        Runs ``litert-lm import <model_path> <model_id>`` via the bundled
        Python runtime.  LiteRT-LM copies the file into the registry selected
        by ``LITERT_LM_DIR``; the original download remains in the add-on's
        model cache.

        Args:
            model_path: Path to the ``.litertlm`` file on disk.
            model_id: The model identifier to register (e.g.
                ``"litert-community/gemma-4-E2B-it-litert-lm"``).
            on_progress: Optional status callback.

        Raises:
            LiteRTServerError: If the import fails.
        """
        python_exe = self._server_python()
        if not python_exe.exists():
            raise LiteRTServerError(
                "Cannot import model — LiteRT runtime is not installed."
            )

        self._report(
            on_progress,
            f"Registering model {model_id} with LiteRT-LM...",
        )

        model_path = Path(model_path)
        if not model_path.is_file():
            raise LiteRTServerError(f"Model file does not exist: {model_path}")
        if not model_id or "\\" in model_id or "\x00" in model_id:
            raise LiteRTServerError(f"Invalid LiteRT-LM model ID: {model_id!r}")

        try:
            result = subprocess.run(
                [
                    str(python_exe),
                    "-m",
                    "litert_lm_cli.main",
                    "import",
                    str(model_path),
                    model_id,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=self._process_environment(),
            )
        except subprocess.TimeoutExpired:
            raise LiteRTServerError(
                f"Model import timed out for {model_id}"
            )
        except Exception as exc:
            raise LiteRTServerError(
                f"Failed to import model {model_id}: {exc}"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise LiteRTServerError(
                f"Model import failed for {model_id}: {stderr}"
            )

        log.info("Model %s imported successfully", model_id)
        if on_progress:
            on_progress(f"Model {model_id} registered.")

    def wait_until_ready(
        self,
        timeout: float = 60.0,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        """Poll the server health endpoint until it responds or *timeout* elapses.

        Returns:
            ``True`` if the server became ready, ``False`` on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running:
                raise LiteRTServerError(
                    "LiteRT server process exited unexpectedly. "
                    "Check the server logs for details."
                )
            if self.is_healthy(timeout=2.0):
                log.info("LiteRT server is ready at %s", self.base_url)
                return True

            self._report(on_progress, "Waiting for LiteRT-LM server to be ready...")
            time.sleep(SERVER_READY_POLL_INTERVAL)

        log.warning("LiteRT server did not become ready within %.0fs", timeout)
        return False

    def shutdown(self) -> None:
        """Stop the server and clean up. Safe to call multiple times."""
        self.stop()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _server_dir(self) -> Path:
        """Return the path to the self-contained runtime directory."""
        return get_runtime_path("litert-lm", self._version)

    def _server_python(self) -> Path:
        """Return the path to the bundled Python executable."""
        return self._server_dir() / "python.exe"

    @staticmethod
    def _litert_dir() -> Path:
        return _default_litert_dir()

    @classmethod
    def _process_environment(cls) -> dict[str, str]:
        env = os.environ.copy()
        env["LITERT_LM_DIR"] = str(cls._litert_dir())
        return env

    @staticmethod
    def _build_download_url(config: RuntimeConfig) -> str:
        """Build the GitHub Releases download URL for a runtime ZIP."""
        return _RUNTIME_DOWNLOAD_BASE.format(version=config.version)

    @staticmethod
    def _report(
        callback: Callable[[str], None] | None,
        message: str,
    ) -> None:
        """Invoke a progress callback if provided."""
        if callback is not None:
            try:
                callback(message)
            except Exception:
                pass
