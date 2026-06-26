# -*- coding: utf-8 -*-
"""Generic runtime loader for on-demand backends.

Loads a runtime package from an extracted bundle by injecting
its path into sys.path for the provider's lifetime.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


class RuntimeLoadError(RuntimeError):
    """Raised when a runtime fails to load."""


class RuntimeImportError(RuntimeLoadError):
    """Raised when the runtime Python package cannot be imported."""


class RuntimeLoader:
    """Loads a runtime Python package from a local bundle path.

    Injects the bundle path into ``sys.path`` and caches the import
    in ``sys.modules`` so the provider can use it throughout its
    lifetime. Call ``unload_package()`` to release the module.
    """

    def __init__(self, runtime_path: str | Path) -> None:
        self._runtime_path = Path(runtime_path)
        if not self._runtime_path.is_dir():
            raise RuntimeLoadError(f"Runtime path does not exist: {runtime_path}")

    def import_package(self, package_name: str) -> ModuleType:
        """Import a package from the runtime path.

        The runtime path is added to ``sys.path`` if not already present.
        Any previously cached module under *package_name* is evicted first
        so the import always reflects the current files on disk.

        Returns:
            The imported module (e.g., ``litert_lm``).

        Raises:
            RuntimeImportError: If the package cannot be imported.
        """
        package_path = str(self._runtime_path)
        if package_path not in sys.path:
            sys.path.insert(0, package_path)

        # Evict stale cached module so we get a fresh import
        sys.modules.pop(package_name, None)

        try:
            return importlib.import_module(package_name)
        except ImportError as exc:
            raise RuntimeImportError(
                f"Failed to import '{package_name}' from {package_path}: {exc}"
            ) from exc

    def unload_package(self, package_name: str) -> None:
        """Remove a previously imported package from ``sys.modules``."""
        sys.modules.pop(package_name, None)
