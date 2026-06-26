#!/usr/bin/env python3
"""Install or bundle a litert-lm runtime for the NVDA AI Assistant.

Downloads the wheel from PyPI and extracts it.

Usage::

    # Dev — extract into the versioned runtime directory
    python scripts/build_runtime_bundle.py 0.13.1

    # Release — build a distributable ZIP in dist/
    python scripts/build_runtime_bundle.py 0.13.1 --release
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PYPI_PACKAGE = "litert-lm-api"
RUNTIME_NAME = "litert-lm"

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _appdata_runtime_dir(version: str) -> Path:
    """``%APPDATA%/nvda/AIAssistant/runtimes/litert-lm/<version>``."""
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "nvda" / "AIAssistant" / "runtimes" / RUNTIME_NAME / version


def _bundle_zip_name(version: str, platform: str) -> str:
    return f"{RUNTIME_NAME}-{version}-{platform}-runtime.zip"


# ---------------------------------------------------------------------------
# Wheel helpers
# ---------------------------------------------------------------------------


def _download_wheel(spec: str, dest_dir: Path) -> Path:
    """Download a wheel from PyPI into *dest_dir*.  Returns the wheel path."""
    subprocess.run(
        [sys.executable, "-m", "pip", "download",
         "--only-binary=:all:", "--no-deps", "--dest", str(dest_dir), spec],
        check=True, capture_output=True, text=True,
    )
    wheels = list(dest_dir.glob("*.whl"))
    if not wheels:
        print("ERROR: No wheel downloaded")
        sys.exit(1)
    return wheels[0]


def _extract_wheel(wheel_path: Path, extract_dir: Path) -> Path:
    """Extract the ``litert_lm/`` package directory from a wheel.

    Returns the path to the extracted ``litert_lm`` directory.
    """
    with zipfile.ZipFile(wheel_path, "r") as zf:
        zf.extractall(extract_dir)
    return extract_dir / "litert_lm"


def _build_manifest(src_dir: Path, version: str, platform: str) -> dict:
    """Scan *src_dir* and return a manifest dict."""
    all_files = sorted(src_dir.rglob("*")) if src_dir.exists() else []
    file_hashes: dict[str, str] = {}
    total_size = 0
    for f in all_files:
        if f.is_file() and f.name != "manifest.json":
            file_hashes[str(f.relative_to(src_dir))] = hashlib.sha256(
                f.read_bytes()
            ).hexdigest()
            total_size += f.stat().st_size

    dll_names = {f.name for f in all_files if f.is_file()}

    return {
        "runtime": RUNTIME_NAME,
        "version": version,
        "platform": platform,
        "python": ">=3.10",
        "arch": "x86_64",
        "cpus": ["cpu"],
        "gpu": "dxcompiler.dll" in dll_names,
        "openvino": "LiteRtDispatch.dll" in dll_names,
        "fileCount": len(file_hashes),
        "totalSizeBytes": total_size,
        "files": file_hashes,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _write_manifest(src_dir: Path, version: str, platform: str) -> Path:
    """Write ``manifest.json`` to *src_dir*."""
    manifest = _build_manifest(src_dir, version, platform)
    path = src_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    mb = manifest["totalSizeBytes"] / 1024 / 1024
    print(f"  manifest.json: {manifest['fileCount']} files, {mb:.1f} MB")
    return path


def _dir_size(directory: Path) -> int:
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


# ---------------------------------------------------------------------------
# Dev workflow — extract wheel into the versioned runtime directory
# ---------------------------------------------------------------------------


def install_dev_runtime(version: str, target_dir: Path) -> Path:
    """Download wheel and extract the ``litert_lm`` package into *target_dir*."""
    spec = f"{PYPI_PACKAGE}=={version}"
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="litert_dev_") as tmp:
        tmp_dir = Path(tmp)
        wheel = _download_wheel(spec, tmp_dir / "wheels")
        src = _extract_wheel(wheel, tmp_dir / "extracted")
        # Merge into target — overwrite all files except locked DLLs
        dst = target_dir / "litert_lm"
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                dest_file = dst / rel
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(item, dest_file)
                except PermissionError:
                    pass  # locked by another process (e.g. litert-lm.dll)

    _write_manifest(target_dir, version, "windows-x64")
    dest_mb = _dir_size(target_dir) / 1024 / 1024
    print(f"\n[dev] LiteRT-LM {version} installed to {target_dir} ({dest_mb:.0f} MB)")
    print("[dev] The addon will load from this directory directly.")
    return target_dir


# ---------------------------------------------------------------------------
# Release workflow — bundle a distributable ZIP
# ---------------------------------------------------------------------------


def build_release_bundle(
    version: str,
    platform: str,
    output_dir: Path,
) -> Path:
    """Download wheel and create a distributable ZIP."""
    spec = f"{PYPI_PACKAGE}=={version}"
    zip_name = _bundle_zip_name(version, platform)

    with tempfile.TemporaryDirectory(prefix="litert_release_") as tmp:
        tmp_dir = Path(tmp)
        wheel = _download_wheel(spec, tmp_dir / "wheels")
        src = _extract_wheel(wheel, tmp_dir / "extracted")

        # Strip GPU DLLs and cruft for release
        for pattern in ["dxcompiler.dll", "dxil.dll", "LiteRtDispatch.dll"]:
            for f in src.rglob(pattern):
                f.unlink()
        vendors = src / "vendors"
        if vendors.exists():
            shutil.rmtree(vendors, ignore_errors=True)
        for pycache in src.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)

        _write_manifest(src, version, platform)

        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in src.rglob("*"):
                if f.is_file():
                    zf.write(f, str(f.relative_to(src)))

        zipped_mb = zip_path.stat().st_size / 1024 / 1024
        extracted_mb = _dir_size(src) / 1024 / 1024
        print(f"\n[release] Bundle created: {zip_path}")
        print(f"[release] {extracted_mb:.1f} MB extracted, {zipped_mb:.1f} MB zipped")
        return zip_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install or bundle litert-lm runtime for NVDA AI Assistant."
    )
    parser.add_argument(
        "version", nargs="?", default="0.13.1",
        help="Runtime version (default: 0.13.1)",
    )
    parser.add_argument(
        "--output-dir", default="dist",
        help="Output directory for release ZIP (default: dist/)",
    )
    parser.add_argument(
        "--release", action="store_true",
        help="Build a distributable ZIP instead of dev-installing",
    )
    parser.add_argument(
        "--runtime-dir", type=Path, default=None,
        help="Target directory (default: %%APPDATA%%/nvda/AIAssistant/runtimes/litert-lm/<version>)",
    )
    args = parser.parse_args()

    if args.release:
        build_release_bundle(
            version=args.version,
            platform="windows-x64",
            output_dir=Path(args.output_dir),
        )
    else:
        install_dev_runtime(
            version=args.version,
            target_dir=args.runtime_dir or _appdata_runtime_dir(args.version),
        )


if __name__ == "__main__":
    main()
