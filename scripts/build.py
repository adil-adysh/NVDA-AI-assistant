# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from importlib.machinery import EXTENSION_SUFFIXES
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
HOST_DIR = ROOT_DIR / "nvda_ui_host"
HOST_DESTINATION = ROOT_DIR / "addon" / "globalPlugins" / "AI-assistant" / "ui_host" / "nvda_ui_host.exe"
MEMORY_ENGINE_DIR = ROOT_DIR / "memory_engine"
LLM_CLIENT_DIR = ROOT_DIR / "llm_client"
ADDON_LIB_DIR = ROOT_DIR / "addon" / "globalPlugins" / "AI-assistant" / "lib"
NPM_EXECUTABLE = "npm.cmd" if os.name == "nt" else "npm"


def build_webui() -> None:
	package_json = HOST_DIR / "package.json"
	if not package_json.exists():
		return

	node_modules = HOST_DIR / "node_modules"
	if not node_modules.exists():
		print("Installing NVDA UI host WebView dependencies: npm ci")
		subprocess.run([NPM_EXECUTABLE, "ci"], cwd=HOST_DIR, check=True)

	print("Building NVDA UI host WebView assets: npm run build:webui")
	subprocess.run([NPM_EXECUTABLE, "run", "build:webui"], cwd=HOST_DIR, check=True)


def _filter_host_rustflags(environment: dict[str, str]) -> dict[str, str]:
	filtered_environment = environment.copy()
	rustflags = filtered_environment.get("RUSTFLAGS", "")
	if rustflags:
		filtered_tokens: list[str] = []
		tokens = rustflags.split()
		i = 0
		while i < len(tokens):
			token = tokens[i]
			if token == "-C" and i + 1 < len(tokens):
				next_token = tokens[i + 1]
				if next_token == "lto" or next_token.startswith("lto="):
					i += 2
					continue
				if next_token.startswith("embed-bitcode="):
					i += 2
					continue
				filtered_tokens.extend([token, next_token])
				i += 2
				continue
			if token.startswith("-Clto") or token.startswith("-Cembed-bitcode"):
				i += 1
				continue
			filtered_tokens.append(token)
			i += 1
		filtered_environment["RUSTFLAGS"] = " ".join(filtered_tokens)
	filtered_environment["CARGO_PROFILE_RELEASE_LTO"] = "false"
	return filtered_environment


def _filtered_rust_environment() -> dict[str, str]:
	return _filter_host_rustflags(os.environ)


def build_host(*, release: bool = True) -> None:
	args = ["cargo", "build"]
	if release:
		args.append("--release")

	print("Building NVDA UI host:", " ".join(args))
	env = _filtered_rust_environment()
	subprocess.run(args, cwd=HOST_DIR, env=env, check=True)


def _find_host_binary() -> Path:
	host_targets = sorted(HOST_DIR.glob("target/**/nvda_ui_host.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
	if not host_targets:
		raise FileNotFoundError(f"Host executable not found under {HOST_DIR / 'target'}.")
	return host_targets[0]


def install_host_binary(*, allow_existing_install: bool = False) -> None:
	try:
		target_exe = _find_host_binary()
	except FileNotFoundError:
		if allow_existing_install and HOST_DESTINATION.exists():
			print(f"Using existing installed host binary at {HOST_DESTINATION}")
			return
		raise

	HOST_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(target_exe, HOST_DESTINATION)
	print(f"Copied host binary to {HOST_DESTINATION}")


def install_host_assets() -> None:
	source_assets = HOST_DIR / "assets"
	if not source_assets.exists():
		raise FileNotFoundError(
			f"Host asset directory not found: {source_assets}. "
			"Create the assets and rebuild the host."
		)

	destination_assets = HOST_DESTINATION.parent / "assets"
	if destination_assets.exists():
		shutil.rmtree(destination_assets)
	shutil.copytree(source_assets, destination_assets)
	print(f"Copied host assets to {destination_assets}")


def build_memory_engine(*, release: bool = True) -> None:
	args = ["cargo", "build", "--manifest-path", str(MEMORY_ENGINE_DIR / "Cargo.toml")]
	if release:
		args.append("--release")

	print("Building memory_engine:", " ".join(args))
	env = _filtered_rust_environment()
	env.setdefault("PYO3_PYTHON", sys.executable)
	# PyO3 0.23.5 caps at Python 3.13; allow forward compat via stable ABI
	env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"
	subprocess.run(args, cwd=ROOT_DIR, env=env, check=True)


def _compiled_memory_engine_path(*, release: bool) -> Path:
	profile_dir = "release" if release else "debug"
	if os.name == "nt":
		pattern = f"target/**/{profile_dir}/memory_engine.dll"
	elif sys.platform == "darwin":
		pattern = f"target/**/{profile_dir}/libmemory_engine.dylib"
	else:
		pattern = f"target/**/{profile_dir}/libmemory_engine.so"
	candidates = sorted(
		MEMORY_ENGINE_DIR.glob(pattern),
		key=lambda path: path.stat().st_mtime,
		reverse=True,
	)
	if not candidates:
		raise FileNotFoundError(
			f"Compiled memory_engine library not found under {MEMORY_ENGINE_DIR / 'target'} for profile {profile_dir}."
		)
	return candidates[0]


def _find_existing_extension() -> Path | None:
	for suffix in EXTENSION_SUFFIXES:
		matches = list(ADDON_LIB_DIR.glob(f"memory_engine*{suffix}"))
		if matches:
			return matches[0]
	return None


def install_memory_engine_extension(*, release: bool, allow_existing_install: bool = False) -> None:
	try:
		built_extension = _compiled_memory_engine_path(release=release)
	except FileNotFoundError:
		if allow_existing_install:
			existing_extension = _find_existing_extension()
			if existing_extension is not None:
				print(f"Using existing installed memory_engine extension at {existing_extension}")
				return
		raise

	ADDON_LIB_DIR.mkdir(parents=True, exist_ok=True)
	for suffix in EXTENSION_SUFFIXES:
		for stale_extension in ADDON_LIB_DIR.glob(f"memory_engine*{suffix}"):
			stale_extension.unlink(missing_ok=True)

	if os.name == "nt":
		destination_name = "memory_engine.pyd"
	else:
		destination_name = built_extension.name.removeprefix("lib")
	destination_path = ADDON_LIB_DIR / destination_name
	shutil.copy2(built_extension, destination_path)
	print(f"Copied memory_engine extension to {destination_path}")


def build_llm_client(*, release: bool = True) -> None:
	args = ["cargo", "build", "--manifest-path", str(LLM_CLIENT_DIR / "Cargo.toml")]
	if release:
		args.append("--release")

	print("Building llm_client:", " ".join(args))
	env = _filtered_rust_environment()
	env.setdefault("PYO3_PYTHON", sys.executable)
	# PyO3 caps at Python 3.13; allow forward compat via stable ABI
	env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"
	subprocess.run(args, cwd=ROOT_DIR, env=env, check=True)


def _compiled_llm_client_path(*, release: bool) -> Path:
	profile_dir = "release" if release else "debug"
	if os.name == "nt":
		pattern = f"target/**/{profile_dir}/llm_client.dll"
	elif sys.platform == "darwin":
		pattern = f"target/**/{profile_dir}/libllm_client.dylib"
	else:
		pattern = f"target/**/{profile_dir}/libllm_client.so"
	candidates = sorted(
		LLM_CLIENT_DIR.glob(pattern),
		key=lambda path: path.stat().st_mtime,
		reverse=True,
	)
	if not candidates:
		raise FileNotFoundError(
			f"Compiled llm_client library not found under {LLM_CLIENT_DIR / 'target'} for profile {profile_dir}."
		)
	return candidates[0]


def _find_existing_llm_client_extension() -> Path | None:
	for suffix in EXTENSION_SUFFIXES:
		matches = list(ADDON_LIB_DIR.glob(f"llm_client*{suffix}"))
		if matches:
			return matches[0]
	return None


def install_llm_client_extension(*, release: bool, allow_existing_install: bool = False) -> None:
	try:
		built_extension = _compiled_llm_client_path(release=release)
	except FileNotFoundError:
		if allow_existing_install:
			existing_extension = _find_existing_llm_client_extension()
			if existing_extension is not None:
				print(f"Using existing installed llm_client extension at {existing_extension}")
				return
		raise

	ADDON_LIB_DIR.mkdir(parents=True, exist_ok=True)
	for suffix in EXTENSION_SUFFIXES:
		for stale_extension in ADDON_LIB_DIR.glob(f"llm_client*{suffix}"):
			stale_extension.unlink(missing_ok=True)

	if os.name == "nt":
		destination_name = "llm_client.pyd"
	else:
		destination_name = built_extension.name.removeprefix("lib")
	destination_path = ADDON_LIB_DIR / destination_name
	shutil.copy2(built_extension, destination_path)
	print(f"Copied llm_client extension to {destination_path}")


def main() -> int:
	parser = argparse.ArgumentParser(description="Build and install Rust artifacts for the NVDA AI Assistant add-on.")
	parser.add_argument("--debug", action="store_true", help="Build Rust artifacts using debug mode.")
	parser.add_argument("--install-only", action="store_true", help="Copy existing built artifacts without rebuilding them.")
	args = parser.parse_args()

	try:
		build_webui()
		if not args.install_only:
			build_host(release=not args.debug)
			build_memory_engine(release=not args.debug)
			build_llm_client(release=not args.debug)
		install_host_binary(allow_existing_install=args.install_only)
		install_host_assets()
		install_memory_engine_extension(release=not args.debug, allow_existing_install=args.install_only)
		install_llm_client_extension(release=not args.debug, allow_existing_install=args.install_only)
	except Exception as error:
		print(f"Rust artifact build failed: {error}")
		return 1

	return 0

if __name__ == "__main__":
	raise SystemExit(main())
