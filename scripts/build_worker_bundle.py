"""Build a private, isolated CPython worker using the locked uv environment."""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import shutil
import sys
import sysconfig
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ADDON_ROOT = ROOT / "addon" / "globalPlugins" / "AI-assistant"
BUNDLE = ADDON_ROOT / "worker_host"
PYTHON_VERSION = "3.13.12"
PYTHON_SHA256 = "76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYWIN32_VERSION = "311"
WIN32_MODULES = ("win32api", "win32event", "win32file", "win32pipe", "win32process", "win32security", "win32job", "_win32sysloader")
REQUIRED = (
	"python.exe", "python313.dll", "python313.zip", "python313._pth",
	"python3.dll", "vcruntime140.dll", "vcruntime140_1.dll",
	"_ssl.pyd", "_socket.pyd", "_hashlib.pyd", "_ctypes.pyd", "select.pyd",
	"runtime_supervisor.pyd", "pywintypes313.dll",
	"pywintypes.py", "win32con.py", "ntsecuritycon.py", "bundle-manifest.json",
	*(f"{name}.pyd" for name in WIN32_MODULES),
)


def forbidden(path: Path) -> bool:
	parts = tuple(part.casefold() for part in path.parts)
	return (
		any(part in {"test", "tests", "fixtures", "__pycache__", ".pytest_cache", "site-packages"} for part in parts)
		or path.name.casefold().startswith("test_")
		or path.name.casefold() in {"conftest.py", "pytest.ini"}
		or path.suffix.casefold() in {".pyc", ".pyo"}
	)


def build_stdlib_archive(source: Path, destination: Path) -> None:
	"""Replace the official bytecode zip with matching standard-library source."""
	with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
		for path in sorted(source.rglob("*.py")):
			relative = path.relative_to(source)
			if not forbidden(relative) and relative.parts[0] not in {"idlelib", "tkinter", "turtledemo", "ensurepip"}:
				archive.writestr(relative.as_posix(), path.read_bytes())


def validate_bundle(path: Path) -> None:
	"""Fail closed on incomplete bundles and test/bytecode artifacts, even in zip."""
	for file in path.rglob("*"):
		if not file.is_file():
			continue
		if forbidden(file.relative_to(path)):
			raise ValueError(f"Worker bundle contains forbidden artifact: {file}")
		if file.suffix == ".zip":
			with zipfile.ZipFile(file) as archive:
				for name in archive.namelist():
					if forbidden(Path(name)) or name.endswith(".zip"):
						raise ValueError(f"Worker bundle contains forbidden archive member: {name}")
	missing = [name for name in REQUIRED if not (path / name).is_file()]
	if missing:
		raise ValueError(f"Worker bundle is missing: {', '.join(missing)}")
	manifest = json.loads((path / "bundle-manifest.json").read_text(encoding="utf-8"))
	if manifest.get("python") != PYTHON_VERSION or manifest.get("pywin32") != PYWIN32_VERSION:
		raise ValueError("Worker bundle versions do not match the locked environment")
	files = manifest.get("files", {})
	if not isinstance(files, dict) or any(name not in files for name in REQUIRED if name != "bundle-manifest.json"):
		raise ValueError("Worker bundle manifest is incomplete")
	for name, checksum in files.items():
		if Path(name).name != name or not (path / name).is_file():
			raise ValueError(f"Worker bundle manifest has missing or invalid file: {name}")
		if checksum != hashlib.sha256((path / name).read_bytes()).hexdigest():
			raise ValueError(f"Worker bundle checksum mismatch: {name}")


def validate_build_environment() -> None:
	if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
		raise RuntimeError("Worker bundle requires Windows amd64")
	try:
		pywin32_version = version("pywin32")
	except PackageNotFoundError:
		pywin32_version = "missing"
	if platform.python_version() != PYTHON_VERSION or pywin32_version != PYWIN32_VERSION:
		raise RuntimeError(
			f"Build requires Python {PYTHON_VERSION} and pywin32 {PYWIN32_VERSION}; "
			f"got Python {platform.python_version()} and pywin32 {pywin32_version} at {sys.executable}. "
			"Run uv sync --locked and build with uv run scons."
		)


def build_worker_bundle(*, allow_existing: bool = False) -> None:
	if allow_existing:
		validate_bundle(BUNDLE)
		return
	validate_build_environment()
	cache = ROOT / "dist" / "worker-build"
	cache.mkdir(parents=True, exist_ok=True)
	archive_path = cache / f"python-{PYTHON_VERSION}-embed-amd64.zip"
	if not archive_path.exists():
		with urllib.request.urlopen(PYTHON_URL, timeout=60) as response, archive_path.open("wb") as output:
			shutil.copyfileobj(response, output)
	if hashlib.sha256(archive_path.read_bytes()).hexdigest() != PYTHON_SHA256:
		raise ValueError("Official worker Python archive checksum mismatch")
	with tempfile.TemporaryDirectory(prefix="bundle-", dir=cache) as staging:
		bundle = Path(staging) / "worker_host"
		bundle.mkdir()
		with zipfile.ZipFile(archive_path) as archive:
			for item in archive.infolist():
				# Official runtime archive is flat; never install its bytecode zip.
				if Path(item.filename).name != item.filename:
					raise ValueError("Unexpected path in official Python archive")
				if item.filename.endswith((".zip", "._pth")):
					continue
				(bundle / item.filename).write_bytes(archive.read(item))
		build_stdlib_archive(Path(sysconfig.get_path("stdlib")), bundle / "python313.zip")
		site = Path(sysconfig.get_path("platlib"))
		for name in WIN32_MODULES:
			shutil.copy2(site / "win32" / f"{name}.pyd", bundle)
		for name in ("pywintypes.py", "win32con.py", "ntsecuritycon.py"):
			shutil.copy2(site / "win32" / "lib" / name, bundle)
		shutil.copy2(site / "pywin32_system32" / "pywintypes313.dll", bundle)
		shutil.copy2(ROOT / "scripts" / "licenses" / "pywin32-311.txt", bundle / "PYWIN32-LICENSE.txt")
		shutil.copy2(ADDON_ROOT / "lib" / "runtime_supervisor.pyd", bundle)
		(bundle / "python313._pth").write_text("python313.zip\n.\n..\n", encoding="utf-8")
		manifest = {
			"python": PYTHON_VERSION, "pywin32": PYWIN32_VERSION,
			"files": {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in bundle.iterdir() if file.is_file()},
		}
		(bundle / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
		validate_bundle(bundle)
		# Complete staging before replacing installed output.
		backup = BUNDLE.with_name("worker_host.previous")
		if backup.exists():
			raise RuntimeError(f"Recover or remove previous bundle before rebuilding: {backup}")
		if BUNDLE.exists():
			BUNDLE.replace(backup)
		try:
			bundle.replace(BUNDLE)
		except BaseException:
			if backup.exists():
				backup.replace(BUNDLE)
			raise
		if backup.exists():
			shutil.rmtree(backup)
	print(f"Installed private CPython worker at {BUNDLE}")


if __name__ == "__main__":
	build_worker_bundle()
