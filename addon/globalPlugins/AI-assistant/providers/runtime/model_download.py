# -*- coding: utf-8 -*-
"""On-demand model file download service.

Downloads ``.litertlm`` model files from Hugging Face (or any
configurable URL), verifies them with SHA-256 when available,
and caches them under the user's model directory.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        on_bytes_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download a model file to the cache directory, with resume support.

        Uses a ``.part`` file that persists across interruptions.  On the
        next attempt the existing partial data is used to issue an HTTP
        ``Range`` request.  If the server does not support range requests
        the download falls back to starting from scratch.

        Args:
            model_name: Local filename for the model (e.g. ``"gemma-4-E2B-it.litertlm"``).
            url: Direct download URL.
            expected_sha256: Optional SHA-256 hex digest for verification.
            on_progress: Optional progress callback receiving text messages.
            on_bytes_progress: Optional callback ``(downloaded_bytes, total_bytes)``
                — during a resume *downloaded_bytes* includes already-cached bytes.

        Returns:
            Path to the downloaded and verified model file.

        Raises:
            ModelDownloadError: If the download or verification fails.
        """
        dest = self._model_path(model_name)
        if dest.exists():
            log.info("Model %s already cached at %s", model_name, dest)
            return dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        part_path = dest.parent / f"{dest.name}.part"

        # Check how much we already have
        existing_bytes = part_path.stat().st_size if part_path.exists() else 0
        is_resume = existing_bytes > 0

        if on_progress:
            msg = f"Resuming {model_name}..." if is_resume else f"Downloading {model_name}..."
            on_progress(msg)

        # Download — append if resuming, write if fresh
        try:
            _download_url_resume(
                url, part_path,
                resume_from=existing_bytes,
                on_bytes_progress=_make_range_aware_progress(
                    on_bytes_progress, existing_bytes,
                ) if on_bytes_progress else None,
            )
        except Exception as exc:
            # Leave .part in place for future resume attempts
            raise ModelDownloadError(
                f"Failed to download {model_name} from {url}: {exc}"
            ) from exc

        # Optional SHA-256 verification
        if expected_sha256:
            if on_progress:
                on_progress(f"Verifying {model_name}...")
            actual = hashlib.sha256(part_path.read_bytes()).hexdigest()
            if actual != expected_sha256:
                _cleanup(part_path)
                raise ModelDownloadError(
                    f"SHA-256 mismatch for {model_name}: "
                    f"expected {expected_sha256}, got {actual}"
                )

        # Atomic rename .part → final name
        part_path.rename(dest)

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


def _download_url_resume(
    url: str,
    dest_path: Path,
    resume_from: int = 0,
    on_bytes_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Stream *url* into *dest_path* with HTTP Range resume and retry.

    When *resume_from* > 0 a ``Range`` header is sent.  If the server
    responds with 206 Partial Content the data is appended.  Otherwise
    (200 OK — range not supported) the file is written from scratch.

    On network failures the connection is retried up to 3 times with
    exponential backoff (1s, 3s, 10s).  Each retry picks up from the
    last byte actually written to disk.

    The *on_bytes_progress* callback receives ``(total_downloaded, total_size)``
    where *total_downloaded* includes the already-cached bytes.
    """
    import time
    import urllib.request

    MAX_RETRIES = 3
    RETRY_DELAYS = (1, 3, 10)

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        # On retry, re-check what's actually on disk
        if attempt > 0:
            resume_from = dest_path.stat().st_size if dest_path.exists() else 0
            delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
            log.warning(
                "Download retry %d/%d for %s after %.0fs (resuming at byte %d)",
                attempt, MAX_RETRIES, dest_path.name, delay, resume_from,
            )
            time.sleep(delay)

        resp: Any | None = None

        try:
            req = urllib.request.Request(url)
            if resume_from > 0:
                req.add_header("Range", f"bytes={resume_from}-")

            resp = urllib.request.urlopen(req, timeout=30)

            status = resp.status
            supports_range = status == 206

            # Server doesn't support Range — restart from scratch
            if resume_from > 0 and not supports_range:
                log.info(
                    "Server does not support Range for %s; re-downloading from scratch",
                    url,
                )
                resume_from = 0
                dest_path.write_bytes(b"")
                resp.close()
                resp = None
                continue

            # Determine total file size for progress reporting
            content_length = resp.length
            if supports_range and content_length is not None:
                total_size = resume_from + content_length
            elif content_length is not None:
                total_size = content_length
            else:
                total_size = 0

            mode = "ab" if resume_from > 0 else "wb"
            downloaded_this_session = 0
            CHUNK_SIZE = 64 * 1024

            with open(dest_path, mode) as f:
                while True:
                    try:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded_this_session += len(chunk)
                        if on_bytes_progress:
                            total_downloaded = resume_from + downloaded_this_session
                            on_bytes_progress(
                                total_downloaded,
                                total_size or total_downloaded,
                            )
                    except Exception as read_err:
                        # Mid-stream failure — retry connection from last byte
                        last_error = read_err
                        if attempt < MAX_RETRIES:
                            log.debug(
                                "Read error on %s at byte %d: %s",
                                dest_path.name,
                                resume_from + downloaded_this_session,
                                read_err,
                            )
                            break  # break inner read loop → retry outer loop
                        raise

                if not chunk and not downloaded_this_session:
                    # EOF right away — might be a transient 0-byte response
                    if attempt < MAX_RETRIES:
                        log.debug(
                            "Empty response on %s (attempt %d), retrying",
                            dest_path.name, attempt,
                        )
                        continue

            # If we hit a read error and broke early, retry the connection
            if last_error is not None and attempt < MAX_RETRIES:
                resp.close()
                resp = None
                continue

            # Success — all data read
            resp.close()
            resp = None
            return

        except urllib.request.HTTPError as exc:
            resp = None
            # 416 Range Not Satisfiable → the .part is already complete
            if exc.code == 416:
                log.debug("Range 416 for %s — part file already complete", dest_path.name)
                if on_bytes_progress:
                    file_size = dest_path.stat().st_size
                    on_bytes_progress(file_size, file_size)
                return
            last_error = exc
            if attempt >= MAX_RETRIES:
                raise
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                raise
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

    # Exhausted retries
    raise ModelDownloadError(
        f"Download failed after {MAX_RETRIES + 1} attempts: {last_error}"
    ) from last_error


def _make_range_aware_progress(
    on_bytes_progress: Callable[[int, int], None] | None,
    existing_bytes: int,
) -> Callable[[int, int], None]:
    """Wrap *on_bytes_progress* to offset for already-cached bytes."""
    if on_bytes_progress is None or existing_bytes == 0:
        return on_bytes_progress

    def _wrapped(downloaded: int, total: int) -> None:
        on_bytes_progress(downloaded, total)

    return _wrapped


def _cleanup(path: Path | None) -> None:
    """Remove *path* if it exists."""
    if path is not None and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
