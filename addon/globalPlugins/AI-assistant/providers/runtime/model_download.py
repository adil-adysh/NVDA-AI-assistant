# -*- coding: utf-8 -*-
"""On-demand model file download service.

Downloads ``.litertlm`` model files from Hugging Face (or any
configurable URL), verifies them with SHA-256 when available,
and caches them under the user's model directory.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from logHandler import log

from ..interfaces import ProgressCallback


HF_DEFAULT_BASE = "https://huggingface.co"


class ModelDownloadError(RuntimeError):
    """Raised when a model download or verification fails."""


class ModelDownloadService:
    """Download and cache ``.litertlm`` model files.

    Parameters:
        cache_dir: Root directory for cached models.  Defaults to
            ``%APPDATA%/nvda/AIAssistant/models/litert-lm/``.
        hf_base_url: Hugging Face base URL.  Override for mirrors.
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        hf_base_url: str = HF_DEFAULT_BASE,
    ) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else _default_model_dir()
        self._hf_base_url = hf_base_url.rstrip("/")

    # ── Public API ──────────────────────────────────────────────────

    def is_downloaded(self, model_name: str) -> bool:
        """Return ``True`` if *model_name* is already cached."""
        return self._model_path(model_name).exists()

    def model_path(self, model_name: str) -> Path:
        """Return the expected local path for *model_name*."""
        return self._model_path(model_name)

    def download(
        self,
        model_name: str,
        url: str,
        expected_sha256: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Download a model file to the cache directory.

        Args:
            model_name: Local filename for the model (e.g. ``"gemma-4-E2B-it.litertlm"``).
            url: Direct download URL.
            expected_sha256: Optional SHA-256 hex digest for verification.
            on_progress: Optional progress callback.

        Returns:
            Path to the downloaded and verified model file.

        Raises:
            ModelDownloadError: If the download or verification fails.
        """
        dest = self._model_path(model_name)
        if dest.exists():
            log.info("Model %s already cached at %s", model_name, dest)
            return dest

        if on_progress:
            on_progress(f"Downloading {model_name}...")

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Download to a temp file next to the final location so the
        # rename is atomic (same filesystem).
        tmp_dir = dest.parent
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".litertlm", dir=tmp_dir
            ) as tmp:
                tmp_path = Path(tmp.name)
                _download_url(url, tmp)
        except Exception as exc:
            _cleanup(tmp_path)
            raise ModelDownloadError(
                f"Failed to download {model_name} from {url}: {exc}"
            ) from exc

        # Optional SHA-256 verification
        if expected_sha256:
            if on_progress:
                on_progress(f"Verifying {model_name}...")
            actual = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
            if actual != expected_sha256:
                _cleanup(tmp_path)
                raise ModelDownloadError(
                    f"SHA-256 mismatch for {model_name}: "
                    f"expected {expected_sha256}, got {actual}"
                )

        # Atomic rename
        tmp_path.rename(dest)

        size_mb = dest.stat().st_size / 1024 / 1024
        log.info("Model %s downloaded to %s (%.1f MB)", model_name, dest, size_mb)
        if on_progress:
            on_progress(f"{model_name} ready ({size_mb:.0f} MB)")

        return dest

    # ── Internal helpers ────────────────────────────────────────────

    def _model_path(self, model_name: str) -> Path:
        """Resolve *model_name* under the cache directory."""
        # Sanitise — strip any path separators to avoid traversal
        safe = model_name.replace("/", "_").replace("\\", "_")
        return self._cache_dir / safe


# ── Module-level helpers ───────────────────────────────────────────


def _default_model_dir() -> Path:
    """``%APPDATA%/nvda/AIAssistant/models/litert-lm/``."""
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "nvda" / "AIAssistant" / "models" / "litert-lm"


def _download_url(url: str, tmp_file) -> None:  # noqa: ANN001
    """Stream *url* into *tmp_file*."""
    import urllib.request

    urllib.request.urlretrieve(url, tmp_file.name)


def _cleanup(path: Path | None) -> None:
    """Remove *path* if it exists."""
    if path is not None and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
