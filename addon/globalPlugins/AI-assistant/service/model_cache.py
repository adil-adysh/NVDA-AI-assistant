# -*- coding: utf-8 -*-
"""Centralized model catalog cache and capability cache.

Provides a thread-safe, lazily-populated cache of ``ProviderModelInfo``
lists and ``ModelCatalogSnapshot`` state keyed by provider ID.  The gesture
layer, model-manager UI, presenter, and provider-control service all read from
this cache instead of maintaining duplicate caches or making repeated network
round-trips.

The cache distinguishes between:
1. ``CatalogState.COLD``: Not yet fetched.
2. ``CatalogState.LOADING``: Fetch currently in progress (waiters deduplicated).
3. ``CatalogState.READY``: Successfully discovered >= 1 models.
4. ``CatalogState.EMPTY``: Successfully discovered 0 models (durable; not retried
   on every read).
5. ``CatalogState.ERROR``: Fetch failed (transient network error, credentials,
   or server offline).

Subscribers can listen for catalog updates via ``subscribe()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from collections.abc import Callable

from logHandler import log

from ..providers.interfaces import ProviderModelInfo
from ..providers.capabilities import ModelCapabilities


class CatalogState(str, Enum):
    COLD = "cold"
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModelCatalogSnapshot:
    """Immutable snapshot of a provider's model catalog state."""

    provider_id: str
    state: CatalogState
    models: tuple[ProviderModelInfo, ...] = ()
    error_message: str | None = None
    version: int = 0


class _FetchGate:
    """Coordinates concurrent fetches for a single provider.

    The first thread to encounter an empty/stale cache entry creates a
    ``_FetchGate``, performs the HTTP fetch, and signals ``event``.
    Subsequent threads wait on ``event`` and read ``result``.
    """

    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: tuple[ProviderModelInfo, ...] = ()
        self.error: Exception | None = None


class ModelCatalogCache:
    """Thread-safe cache of ``ProviderModelInfo`` per provider.

    All read operations are non-blocking once populated.  The first
    ``get_models()`` call for a provider may block while it fetches
    from the network, but subsequent calls return instantly.

    Call ``preload_all()`` during startup to warm the cache in the
    background without blocking NVDA initialization.
    """

    def __init__(
        self,
        catalog_factory: Callable[[], object] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        # Entry types:
        #   None / missing        → not yet fetched (COLD)
        #   _FetchGate            → fetch in progress (LOADING)
        #   ModelCatalogSnapshot  → cached snapshot (READY, EMPTY, or ERROR)
        self._entries: dict[str, ModelCatalogSnapshot | _FetchGate] = {}
        self._generations: dict[str, int] = {}
        self._subscribers: list[Callable[[str, ModelCatalogSnapshot], None]] = []
        self._catalog_factory = catalog_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_models(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Return cached models for *provider_id*.

        If the cache is cold or in error for this provider, fetches synchronously
        (blocking).  Once populated, returns instantly.

        If another thread is already fetching *provider_id*, this call
        waits for that fetch to complete instead of starting a duplicate
        request.
        """
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            entry = self._entries.get(provider_id)

        if isinstance(entry, ModelCatalogSnapshot):
            if entry.state is CatalogState.READY:
                return entry.models
            if entry.state is CatalogState.EMPTY:
                return ()
            # State is ERROR: retry synchronously
            self.invalidate(provider_id)

        return self._fetch_and_cache(provider_id)

    def get_models_or_empty(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Return cached models, or ``()`` if not yet populated.

        Never blocks — safe to call from the NVDA main thread.
        """
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            entry = self._entries.get(provider_id)
        if isinstance(entry, ModelCatalogSnapshot) and entry.state is CatalogState.READY:
            return entry.models
        return ()

    def get_snapshot(self, provider_id: str) -> ModelCatalogSnapshot:
        """Return an immutable snapshot of catalog state.

        Never blocks — safe to call from the NVDA main thread.
        """
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            entry = self._entries.get(provider_id)
            version = self._generations.get(provider_id, 0)

        if isinstance(entry, ModelCatalogSnapshot):
            return entry
        if isinstance(entry, _FetchGate):
            return ModelCatalogSnapshot(provider_id, CatalogState.LOADING, version=version)
        return ModelCatalogSnapshot(provider_id, CatalogState.COLD, version=version)

    def has(self, provider_id: str) -> bool:
        """Return ``True`` if models are successfully cached (READY or EMPTY)."""
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            entry = self._entries.get(provider_id)
        return isinstance(entry, ModelCatalogSnapshot) and entry.state in (
            CatalogState.READY,
            CatalogState.EMPTY,
        )

    def version(self, provider_id: str) -> int:
        """Return the invalidation version for *provider_id*."""
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            return self._generations.get(provider_id, 0)

    def subscribe(
        self,
        callback: Callable[[str, ModelCatalogSnapshot], None],
    ) -> Callable[[], None]:
        """Subscribe to catalog updates.

        *callback* is called with ``(provider_id, snapshot)`` whenever a
        fetch completes.  Returns a 0-arg unsubscription callable.
        """
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def preload_all(self) -> None:
        """Warm the cache for all enabled providers in a background thread."""
        thread = threading.Thread(
            target=self._preload_background,
            name="ModelCatalogPreload",
            daemon=True,
        )
        thread.start()

    def preload_async(self, provider_id: str) -> None:
        """Fetch models for *provider_id* in a background thread if not already cached."""
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            current = self._entries.get(provider_id)
            if isinstance(current, ModelCatalogSnapshot) and current.state in (
                CatalogState.READY,
                CatalogState.EMPTY,
            ):
                return  # Already cached.
            if isinstance(current, _FetchGate):
                return  # Already fetching.
            gate = _FetchGate()
            self._entries[provider_id] = gate

        thread = threading.Thread(
            target=self._fetch_background,
            args=(provider_id, gate),
            name=f"ModelCatalogFetch-{provider_id}",
            daemon=True,
        )
        thread.start()

    def invalidate(self, provider_id: str) -> None:
        """Clear the cache for *provider_id*."""
        provider_id = self._normalize_id(provider_id)
        with self._lock:
            self._entries.pop(provider_id, None)
            self._generations[provider_id] = self._generations.get(provider_id, 0) + 1
        log.debug("ModelCatalogCache: invalidated cache for '%s'", provider_id)

    def invalidate_all(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._entries.clear()
            for provider_id in tuple(self._generations):
                self._generations[provider_id] += 1
        log.debug("ModelCatalogCache: invalidated all caches")

    def refresh_async(self, provider_id: str) -> None:
        """Force a background refresh of *provider_id*."""
        provider_id = self._normalize_id(provider_id)
        self.invalidate(provider_id)
        self.preload_async(provider_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_id(provider_id: str) -> str:
        return str(provider_id or "").strip().lower()

    def _get_catalog(self):
        """Lazy-import and construct the ProviderCatalogService."""
        if self._catalog_factory is not None:
            return self._catalog_factory()
        from .provider_catalog import ProviderCatalogService

        return ProviderCatalogService()

    def _fetch_and_cache(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Fetch models synchronously, cache snapshot, and return."""
        with self._lock:
            entry = self._entries.get(provider_id)
            if isinstance(entry, ModelCatalogSnapshot):
                if entry.state is CatalogState.READY:
                    return entry.models
                if entry.state is CatalogState.EMPTY:
                    return ()
            if isinstance(entry, _FetchGate):
                gate = entry
                is_owner = False
            else:
                gate = _FetchGate()
                self._entries[provider_id] = gate
                is_owner = True

        if is_owner:
            models: tuple[ProviderModelInfo, ...] = ()
            error: Exception | None = None
            try:
                models = self._perform_fetch(provider_id)
            except Exception as exc:
                log.exception("ModelCatalogCache: unexpected fetch failure for '%s'", provider_id)
                error = exc
            self._finish_fetch(provider_id, gate, models, error=error)
            return models
        else:
            gate.event.wait()
            with self._lock:
                final = self._entries.get(provider_id)
                if isinstance(final, ModelCatalogSnapshot):
                    return final.models
                return self._fetch_and_cache(provider_id)

    def _perform_fetch(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Actually perform the catalog fetch."""
        log.debug("ModelCatalogCache: fetching models for '%s'", provider_id)
        catalog = self._get_catalog()
        from ..config.settings import build_provider_config

        config = build_provider_config(provider_id)
        models = tuple(catalog.list_models(config) or ())
        log.debug(
            "ModelCatalogCache: cached %d models for '%s'",
            len(models),
            provider_id,
        )
        return models

    def _finish_fetch(
        self,
        provider_id: str,
        gate: _FetchGate,
        models: tuple[ProviderModelInfo, ...],
        error: Exception | None = None,
    ) -> None:
        """Publish a fetch result and notify subscribers."""
        with self._lock:
            version = self._generations.get(provider_id, 0)
            if error is not None:
                snapshot = ModelCatalogSnapshot(
                    provider_id=provider_id,
                    state=CatalogState.ERROR,
                    models=(),
                    error_message=str(error),
                    version=version,
                )
            elif not models:
                snapshot = ModelCatalogSnapshot(
                    provider_id=provider_id,
                    state=CatalogState.EMPTY,
                    models=(),
                    version=version,
                )
            else:
                snapshot = ModelCatalogSnapshot(
                    provider_id=provider_id,
                    state=CatalogState.READY,
                    models=models,
                    version=version,
                )

            if self._entries.get(provider_id) is gate:
                self._entries[provider_id] = snapshot
            subscribers = list(self._subscribers)

        gate.result = models
        gate.error = error
        gate.event.set()

        for subscriber in subscribers:
            try:
                subscriber(provider_id, snapshot)
            except Exception:
                log.exception("ModelCatalogCache: error in subscriber callback")

    def _preload_background(self) -> None:
        try:
            from ..config.settings import get_enabled_providers

            providers = get_enabled_providers()
        except Exception:
            log.exception("ModelCatalogCache: failed to read enabled providers")
            return

        for provider_id in providers:
            try:
                self._fetch_and_cache(provider_id)
            except Exception:
                log.exception(
                    "ModelCatalogCache: preload failed for '%s'",
                    provider_id,
                )

    def _fetch_background(self, provider_id: str, gate: _FetchGate) -> None:
        models: tuple[ProviderModelInfo, ...] = ()
        error: Exception | None = None
        try:
            models = self._perform_fetch(provider_id)
        except Exception as exc:
            log.exception(
                "ModelCatalogCache: background fetch failed for '%s'",
                provider_id,
            )
            error = exc

        self._finish_fetch(provider_id, gate, models, error=error)


class ModelCapabilityCache:
    """Cache normalized capabilities independently from model presentation.

    Protects against capability downgrade when catalog fetch fails or is
    in an error state.
    """

    def __init__(self, catalog_cache: ModelCatalogCache) -> None:
        self._catalog_cache = catalog_cache
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], tuple[int, ModelCapabilities]] = {}

    def get(self, provider_id: str, model_id: str) -> ModelCapabilities:
        key = (provider_id.strip().lower(), model_id.strip())
        catalog_version = self._catalog_cache.version(key[0])
        with self._lock:
            cached = self._entries.get(key)
        if cached is not None and cached[0] == catalog_version:
            return cached[1]

        snapshot = self._catalog_cache.get_snapshot(key[0])
        if snapshot.state in (CatalogState.COLD, CatalogState.ERROR):
            # Synchronous fetch attempt
            self._catalog_cache.get_models(key[0])
            snapshot = self._catalog_cache.get_snapshot(key[0])

        # If discovery failed with ERROR, do NOT downgrade capabilities or cache empty flags
        if snapshot.state is CatalogState.ERROR:
            if cached is not None:
                return cached[1]
            return ModelCapabilities()

        models = snapshot.models
        capabilities = ModelCapabilities()
        for model in models:
            if model.id == key[1]:
                capabilities = ModelCapabilities.from_iterable(model.capabilities)
                break
        with self._lock:
            current = self._entries.get(key)
            if current is not None and current[0] == catalog_version:
                return current[1]
            self._entries[key] = (catalog_version, capabilities)
            return capabilities

    def invalidate(self, provider_id: str, model_id: str | None = None) -> None:
        provider = provider_id.strip().lower()
        with self._lock:
            if model_id is None:
                for key in [key for key in self._entries if key[0] == provider]:
                    del self._entries[key]
                return
            self._entries.pop((provider, model_id.strip()), None)

    def invalidate_all(self) -> None:
        """Drop all capability entries without touching catalog generations."""
        with self._lock:
            self._entries.clear()


# Singleton instances for the add-on lifecycle.
model_catalog_cache = ModelCatalogCache()
model_capability_cache = ModelCapabilityCache(model_catalog_cache)
