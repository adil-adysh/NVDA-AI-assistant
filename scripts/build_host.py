# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST_DIR = ROOT / "nvda_ui_host"
DESTINATION = ROOT / "addon" / "globalPlugins" / "AI-assistant" / "ui_host" / "nvda_ui_host.exe"
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


def find_target_exe() -> Path:
    release_dirs = list(HOST_DIR.glob("target/**/release/nvda_ui_host.exe"))
    if release_dirs:
        return release_dirs[0]
    return HOST_DIR / "target" / "release" / "nvda_ui_host.exe"


def build_host(release: bool = True) -> None:
    args = ["cargo", "build"]
    if release:
        args.append("--release")

    env = os.environ.copy()
    rustflags = env.get("RUSTFLAGS", "")
    if rustflags:
        filtered = []
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
                filtered.extend([token, next_token])
                i += 2
                continue
            if token.startswith("-Clto") or token.startswith("-Cembed-bitcode"):
                i += 1
                continue
            filtered.append(token)
            i += 1
        env["RUSTFLAGS"] = " ".join(filtered)

    env["CARGO_PROFILE_RELEASE_LTO"] = "false"

    print("Building NVDA UI host:", " ".join(args))
    subprocess.run(args, cwd=HOST_DIR, env=env, check=True)


def install_host_binary(*, allow_existing_install: bool = False) -> None:
    target_exe = find_target_exe()
    if not target_exe.exists():
        if allow_existing_install and DESTINATION.exists():
            print(f"Using existing installed host binary at {DESTINATION}")
            return
        raise FileNotFoundError(
            f"Host executable not found: {target_exe}. "
            "Run this script after building the Rust host."
        )

    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_exe, DESTINATION)
    print(f"Copied host binary to {DESTINATION}")


def install_host_assets() -> None:
    source_assets = HOST_DIR / "assets"
    if not source_assets.exists():
        raise FileNotFoundError(
            f"Host asset directory not found: {source_assets}. "
            "Create the assets and rebuild the host."
        )

    destination_assets = DESTINATION.parent / "assets"
    if destination_assets.exists():
        shutil.rmtree(destination_assets)
    shutil.copytree(source_assets, destination_assets)
    print(f"Copied host assets to {destination_assets}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and install the NVDA UI host binary.")
    parser.add_argument("--debug", action="store_true", help="Build the host using cargo debug mode.")
    parser.add_argument("--install-only", action="store_true", help="Copy the existing built host binary without rebuilding.")
    args = parser.parse_args()

    try:
        build_webui()
        if not args.install_only:
            build_host(release=not args.debug)
        install_host_binary(allow_existing_install=args.install_only)
        install_host_assets()
    except subprocess.CalledProcessError as error:
        print(f"Host build failed: {error}")
        return 1
    except Exception as error:
        print(f"Host install failed: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
