#!/usr/bin/env python3
"""Build a self-contained litert-lm runtime bundle for the NVDA AI Assistant.

Downloads the Python 3.13 embeddable distribution, installs litert-lm into
it, and packages everything as a single ZIP that can be extracted and used
without any system Python dependency.

Usage::

    # Dev — build into the versioned runtime directory for local testing
    python scripts/build_runtime_bundle.py 0.15.0

    # Release — build a distributable ZIP in dist/
    python scripts/build_runtime_bundle.py 0.15.0 --release
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYTHON_VERSION = "3.13.12"
PYTHON_EMBED_URL = (
	f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
	f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
LITERT_PACKAGE = "litert-lm"
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


def _dir_size(directory: Path) -> int:
	return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _download_file(url: str, dest: Path) -> None:
	"""Download a file from *url* to *dest*."""
	import urllib.request

	print(f"  Downloading {url}")
	urllib.request.urlretrieve(url, str(dest))
	print(f"  -> {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")


# ---------------------------------------------------------------------------
# Python embeddable setup
# ---------------------------------------------------------------------------


def _configure_embeddable(python_dir: Path) -> None:
	"""Edit ``python313._pth`` to uncomment ``import site``.

	Without this, pip-installed packages in ``Lib/site-packages`` are
	not discoverable.
	"""
	pth = python_dir / "python313._pth"
	if not pth.exists():
		print("  WARNING: python313._pth not found — site-packages may not work")
		return
	lines = pth.read_text(encoding="utf-8").splitlines()
	new_lines = []
	for line in lines:
		stripped = line.strip()
		if stripped == "#import site":
			new_lines.append("import site")
		else:
			new_lines.append(line)
	pth.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
	print("  Configured python313._pth (import site enabled)")


def _bootstrap_pip(python_exe: Path) -> None:
	"""Download ``get-pip.py`` and run it inside the embeddable Python."""
	with tempfile.TemporaryDirectory(prefix="pip_bootstrap_") as tmp:
		tmp_dir = Path(tmp)
		get_pip = tmp_dir / "get-pip.py"
		_download_file(GET_PIP_URL, get_pip)
		subprocess.run(
			[str(python_exe), str(get_pip), "--no-warn-script-location"],
			check=True,
			capture_output=True,
			text=True,
			timeout=120,
		)
	print("  Pip bootstrapped successfully")


def _install_litert(python_exe: Path, version: str) -> None:
	"""``pip install litert-lm==<version>`` into the embeddable Python."""
	pip = python_exe.parent / "Scripts" / "pip.exe"
	subprocess.run(
		[str(pip), "install", "--no-cache-dir", f"{LITERT_PACKAGE}=={version}"],
		check=True,
		capture_output=True,
		text=True,
		timeout=300,
	)
	print(f"  Installed {LITERT_PACKAGE}=={version}")


def _strip_pip(python_dir: Path) -> None:
	"""Remove pip, setuptools, and wheel to reduce bundle size.

	Only used for release bundles; dev builds keep pip for debugging.
	"""
	site_packages = python_dir / "Lib" / "site-packages"
	if not site_packages.exists():
		return

	patterns = [
		"pip",
		"pip-*.dist-info",
		"setuptools",
		"setuptools-*.dist-info",
		"wheel",
		"wheel-*.dist-info",
	]
	for pattern in patterns:
		for p in site_packages.glob(pattern):
			if p.is_dir():
				shutil.rmtree(p, ignore_errors=True)
			else:
				p.unlink(missing_ok=True)

	scripts = python_dir / "Scripts"
	if scripts.exists():
		shutil.rmtree(scripts, ignore_errors=True)

	print("  Stripped pip / setuptools / wheel")


def _clean_pycache(root: Path) -> None:
	"""Remove all ``__pycache__`` directories under *root*."""
	count = 0
	for pycache in root.rglob("__pycache__"):
		shutil.rmtree(pycache, ignore_errors=True)
		count += 1
	if count:
		print(f"  Removed {count} __pycache__ directories")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _build_manifest(src_dir: Path, version: str, platform: str) -> dict:
	"""Scan *src_dir* and return a manifest dict with file hashes."""
	all_files = sorted(src_dir.rglob("*"))
	file_hashes: dict[str, str] = {}
	total_size = 0
	for f in all_files:
		if f.is_file() and f.name != "manifest.json":
			# Use forward slashes for cross-platform consistency
			rel = str(f.relative_to(src_dir)).replace("\\", "/")
			file_hashes[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
			total_size += f.stat().st_size

	return {
		"runtime": RUNTIME_NAME,
		"version": version,
		"platform": platform,
		"python": f">={PYTHON_VERSION}",
		"arch": "x86_64",
		"cpus": ["cpu"],
		"gpu": False,
		"openvino": False,
		"fileCount": len(file_hashes),
		"totalSizeBytes": total_size,
		"files": file_hashes,
		"built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
	}


def _write_manifest(src_dir: Path, version: str, platform: str) -> Path:
	"""Write ``manifest.json`` to *src_dir* and return its path."""
	manifest = _build_manifest(src_dir, version, platform)
	path = src_dir / "manifest.json"
	path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
	mb = manifest["totalSizeBytes"] / 1024 / 1024
	print(f"  manifest.json: {manifest['fileCount']} files, {mb:.1f} MB")
	return path


# ---------------------------------------------------------------------------
# Build workflows
# ---------------------------------------------------------------------------


def _build_runtime(version: str, work_dir: Path, *, strip: bool) -> None:
	"""Shared build pipeline: download Python embeddable, configure, install.

	Args:
		version: litert-lm version to install.
		work_dir: Temporary working directory to build into.
		strip: If True, remove pip/setuptools/wheel after install.
	"""
	# 1. Download and extract Python embeddable
	embed_zip = work_dir / "python-embed-amd64.zip"
	_download_file(PYTHON_EMBED_URL, embed_zip)

	python_dir = work_dir / "python"
	python_dir.mkdir()
	with zipfile.ZipFile(embed_zip, "r") as zf:
		zf.extractall(python_dir)
	print(f"  Extracted Python {PYTHON_VERSION} embeddable ({_dir_size(python_dir) / 1024 / 1024:.1f} MB)")

	# 2. Enable site-packages
	_configure_embeddable(python_dir)

	# 3. Bootstrap pip
	python_exe = python_dir / "python.exe"
	_bootstrap_pip(python_exe)

	# 4. Install litert-lm
	_install_litert(python_exe, version)

	# 5. Clean up
	if strip:
		_strip_pip(python_dir)
	_clean_pycache(python_dir)


def install_dev_runtime(version: str, target_dir: Path) -> Path:
	"""Build the self-contained runtime and place it in *target_dir*.

	Returns the populated target directory.
	"""
	target_dir.mkdir(parents=True, exist_ok=True)

	with tempfile.TemporaryDirectory(prefix="litert_dev_") as tmp:
		tmp_dir = Path(tmp)
		_build_runtime(version, tmp_dir, strip=False)

		python_dir = tmp_dir / "python"
		_write_manifest(python_dir, version, "windows-x64")

		# Replace target atomically
		if target_dir.exists():
			shutil.rmtree(target_dir, ignore_errors=True)
		shutil.copytree(python_dir, target_dir)

	size_mb = _dir_size(target_dir) / 1024 / 1024
	print(f"\n[dev] LiteRT-LM {version} installed to {target_dir} ({size_mb:.0f} MB)")
	print("[dev] The addon will load from this directory directly.")
	return target_dir


def build_release_bundle(
	version: str,
	platform: str,
	output_dir: Path,
) -> Path:
	"""Build a distributable ZIP of the self-contained runtime.

	Returns the path to the created ZIP file.
	"""
	with tempfile.TemporaryDirectory(prefix="litert_release_") as tmp:
		tmp_dir = Path(tmp)
		_build_runtime(version, tmp_dir, strip=True)

		python_dir = tmp_dir / "python"
		_write_manifest(python_dir, version, platform)

		# Create ZIP — files at the root of the archive
		output_dir.mkdir(parents=True, exist_ok=True)
		zip_name = _bundle_zip_name(version, platform)
		zip_path = output_dir / zip_name
		with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
			for f in python_dir.rglob("*"):
				if f.is_file():
					zf.write(f, str(f.relative_to(python_dir)))

		extracted_mb = _dir_size(python_dir) / 1024 / 1024
		zipped_mb = zip_path.stat().st_size / 1024 / 1024
		print(f"\n[release] {extracted_mb:.1f} MB extracted, {zipped_mb:.1f} MB zipped")
		print(f"[release] Bundle: {zip_path}")
		return zip_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Build self-contained litert-lm runtime bundle for NVDA AI Assistant."
	)
	parser.add_argument(
		"version",
		nargs="?",
		default="0.15.0",
		help="Runtime version (default: 0.15.0)",
	)
	parser.add_argument(
		"--output-dir",
		default="dist",
		help="Output directory for release ZIP (default: dist/)",
	)
	parser.add_argument(
		"--release",
		action="store_true",
		help="Build a distributable ZIP instead of dev-installing",
	)
	parser.add_argument(
		"--runtime-dir",
		type=Path,
		default=None,
		help=(
			"Target directory "
			"(default: %%APPDATA%%/nvda/AIAssistant/runtimes/litert-lm/<version>)"
		),
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
