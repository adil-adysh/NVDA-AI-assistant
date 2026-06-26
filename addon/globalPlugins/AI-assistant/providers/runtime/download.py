# -*- coding: utf-8 -*-
"""On-demand runtime download service.

Downloads runtime ZIPs from a configurable URL, verifies SHA-256,
and extracts them to the versioned runtime directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from logHandler import log

from ..interfaces import ProgressCallback
from .config import RuntimeConfig
from .paths import get_runtime_path


class RuntimeDownloadError(RuntimeError):
    """Raised when a runtime download or verification fails."""


def _default_url_builder(config: RuntimeConfig) -> str:
    """Default URL builder for runtime ZIPs hosted on GitHub Releases."""
    return (
        f"https://github.com/nvda-addons/NVDA-AI-assistant/releases/download/"
        f"runtimes/{config.runtime}-{config.version}-{config.platform}-runtime.zip"
    )


class RuntimeDownloadService:
    """Downloads and verifies runtime backend bundles.

    The service fetches a ZIP from a URL (built via a configurable
    builder function), verifies its file hashes against the embedded
    ``manifest.json``, and extracts it to a versioned path.

    Parameters:
        url_builder: A callable ``(RuntimeConfig) -> str`` that returns
            the download URL. Defaults to a GitHub Releases template.
    """

    def __init__(
        self,
        url_builder: Callable[[RuntimeConfig], str] | None = None,
    ) -> None:
        self._url_builder = url_builder or _default_url_builder

    def is_downloaded(self, runtime: str, version: str) -> bool:
        """Check if the runtime is already present and valid."""
        runtime_path = get_runtime_path(runtime, version)
        manifest_path = runtime_path / "manifest.json"
        if not manifest_path.exists():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return manifest.get("version") == version
        except (json.JSONDecodeError, OSError):
            return False

    def download(
        self,
        runtime: str,
        version: str,
        platform: str = "windows-x64",
        url: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Download, verify, and extract a runtime bundle.

        Args:
            runtime: Runtime identifier (e.g., ``"litert-lm"``).
            version: Semantic version string.
            platform: Target platform identifier.
            url: Explicit download URL. If ``None``, built from
                the configured ``url_builder``.
            on_progress: Optional callback receiving status strings.

        Returns:
            Path to the extracted runtime directory.

        Raises:
            RuntimeDownloadError: If download, verification, or
                extraction fails.
        """
        config = RuntimeConfig(
            runtime=runtime, version=version, platform=platform
        )
        runtime_path = get_runtime_path(runtime, version)

        if self.is_downloaded(runtime, version):
            log.info("Runtime %s %s already present at %s", runtime, version, runtime_path)
            return runtime_path

        if on_progress:
            on_progress(f"Downloading {runtime} {version}...")

        download_url = url or self._url_builder(config)

        # Download to a temporary file
        try:
            import urllib.request

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_path = tmp.name
                urllib.request.urlretrieve(download_url, tmp.name)
        except Exception as exc:
            raise RuntimeDownloadError(
                f"Failed to download {runtime} {version} from {download_url}: {exc}"
            ) from exc

        try:
            return self._extract_and_verify(
                tmp_path, runtime, version, platform, on_progress
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_manifest_root(extract_dir: Path) -> Path:
        """Walk *extract_dir* to find the directory holding ``manifest.json``.

        Returns the directory (could be *extract_dir* itself or a child).
        Raises ``RuntimeDownloadError`` if no manifest is found.
        """
        candidates = [extract_dir]
        candidates.extend(extract_dir.iterdir())
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            if (candidate / "manifest.json").exists():
                return candidate
        raise RuntimeDownloadError("ZIP is missing manifest.json")

    @staticmethod
    def _verify_manifest(
        manifest: Any,
        runtime: str,
        version: str,
        platform: str,
    ) -> None:
        """Validate manifest fields match expected values."""
        errors: list[str] = []
        if manifest.runtime != runtime:
            errors.append(
                f"expected runtime '{runtime}', got '{manifest.runtime}'"
            )
        if manifest.version != version:
            errors.append(
                f"expected version '{version}', got '{manifest.version}'"
            )
        if manifest.platform != platform:
            errors.append(
                f"expected platform '{platform}', got '{manifest.platform}'"
            )
        if errors:
            raise RuntimeDownloadError(
                f"Manifest validation failed: {'; '.join(errors)}"
            )

    @staticmethod
    def _verify_file_hashes(
        root: Path,
        files: dict[str, str],
    ) -> None:
        """Check every file in *files* exists under *root* and matches SHA-256."""
        for rel_path, expected_hash in files.items():
            full_path = root / rel_path
            if not full_path.exists():
                raise RuntimeDownloadError(f"Missing file in bundle: {rel_path}")
            actual_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise RuntimeDownloadError(
                    f"SHA-256 mismatch for {rel_path}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

    @staticmethod
    def _atomic_move(source: Path, destination: Path) -> None:
        """Replace *destination* with *source* atomically (best-effort)."""
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)

    def _extract_and_verify(
        self,
        zip_path: str,
        runtime: str,
        version: str,
        platform: str,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Extract ZIP and verify the manifest."""
        runtime_path = get_runtime_path(runtime, version)

        if on_progress:
            on_progress(f"Extracting {runtime} {version}...")

        with tempfile.TemporaryDirectory(prefix=f"{runtime}_extract_") as tmp_dir:
            tmp_path = Path(tmp_dir)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_path)

            if not any(tmp_path.iterdir()):
                raise RuntimeDownloadError("ZIP was empty")

            extracted_root = self._resolve_manifest_root(tmp_path)

            manifest_data = json.loads(
                (extracted_root / "manifest.json").read_text(encoding="utf-8")
            )
            manifest = _manifest_from_dict(manifest_data)

            self._verify_manifest(manifest, runtime, version, platform)

            if on_progress:
                on_progress(f"Verifying {runtime} {version}...")
            self._verify_file_hashes(extracted_root, manifest.files)

            self._atomic_move(extracted_root, runtime_path)

        if on_progress:
            on_progress(f"{runtime} {version} ready")

        log.info("Runtime %s %s extracted to %s", runtime, version, runtime_path)
        return runtime_path


# ------------------------------------------------------------------
# Module-level helpers (no class coupling needed)
# ------------------------------------------------------------------


def _manifest_from_dict(data: dict[str, Any]) -> Any:
    """Deserialize and validate a manifest dict.

    Re-imported here instead of from ``.config`` to avoid circular
    dependency risk and keep the download module self-contained for
    the deserialisation concern.
    """
    from .config import DownloadManifest  # noqa: PLC0415

    return DownloadManifest.from_dict(data)
