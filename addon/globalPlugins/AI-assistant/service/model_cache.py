# -*- coding: utf-8 -*-
"""Centralized model catalog cache.

Provides a thread-safe, lazily-populated cache of ``ProviderModelInfo``
lists keyed by provider ID.  The gesture layer, model-manager UI, and
provider-control service all read from this cache instead of making
repeated network round-trips.

The cache is populated:
1. On startup — ``preload_all()`` runs in a background thread for all
   enabled providers.
2. On first access — if a provider's cache is empty, ``get_models()``
   blocks briefly on first call and populates it.
3. On explicit invalidation — ``invalidate()`` clears a provider's
   entry so the next read triggers a refresh.

Concurrent fetches for the same provider are **deduplicated**: only one
HTTP request is in flight at a time; other callers wait on a
``threading.Event`` and receive the same result.

Usage::

    from ..service.model_cache import model_catalog_cache

    models = model_catalog_cache.get_models("ollama")
    model_catalog_cache.invalidate("ollama")
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from logHandler import log

from ..providers.interfaces import ProviderModelInfo


class _FetchGate:
    """Coordinates concurrent fetches for a single provider.

    The first thread to encounter an empty cache entry creates a
    ``_FetchGate``, performs the HTTP fetch, and signals ``event``.
    Subsequent threads wait on ``event`` and read ``result``.
    """

    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: tuple[ProviderModelInfo, ...] = ()


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
        """*catalog_factory* is a 0-arg callable that returns a
        ``ProviderCatalogService`` (lazy import to avoid circular deps).
        """
        self._lock = threading.RLock()
        # Entry types:
        #   None / missing  → not yet fetched
        #   _FetchGate      → fetch in progress (other threads wait)
        #   tuple[...]      → cached result
        self._entries: dict[str, tuple[ProviderModelInfo, ...] | _FetchGate] = {}
        self._catalog_factory = catalog_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_models(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Return cached models for *provider_id*.

        If the cache is empty for this provider, fetches synchronously
        (blocking).  Once populated, returns instantly.

        If another thread is already fetching *provider_id*, this call
        waits for that fetch to complete instead of starting a duplicate
        request.
        """
        entry = self._entries.get(provider_id)
        if isinstance(entry, tuple):
            return entry

        # Not cached yet — fetch synchronously (deduplicated).
        return self._fetch_and_cache(provider_id)

    def get_models_or_empty(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Return cached models, or ``()`` if not yet populated.

        Never blocks — safe to call from the NVDA main thread.
        """
        entry = self._entries.get(provider_id)
        if isinstance(entry, tuple):
            return entry
        return ()

    def has(self, provider_id: str) -> bool:
        """Return ``True`` if models are cached for *provider_id*."""
        entry = self._entries.get(provider_id)
        return isinstance(entry, tuple)

    def preload_all(self) -> None:
        """Warm the cache for all enabled providers in a background thread.

        Safe to call during plugin initialization.  The thread is a
        daemon so it will not prevent NVDA from shutting down.
        """
        thread = threading.Thread(
            target=self._preload_background,
            name="ModelCatalogPreload",
            daemon=True,
        )
        thread.start()

    def preload_async(self, provider_id: str) -> None:
        """Fetch models for *provider_id* in a background thread.

        Subsequent ``get_models(provider_id)`` calls will see the
        results once the fetch completes.  If another thread is
        already fetching *provider_id*, this is a no-op.
        """
        with self._lock:
            current = self._entries.get(provider_id)
            if isinstance(current, tuple):
                return  # Already cached.
            if isinstance(current, _FetchGate):
                return  # Already fetching.
            gate = _FetchGate()
            self._entries[provider_id] = gate

        thread = threading.Thread(
            target=self._fetch_background,
            args=(provider_id,),
            name=f"ModelCatalogFetch-{provider_id}",
            daemon=True,
        )
        thread.start()

    def invalidate(self, provider_id: str) -> None:
        """Clear the cache for *provider_id*.

        The next ``get_models()`` call will fetch fresh data.
        """
        with self._lock:
            self._entries.pop(provider_id, None)
        log.debug("ModelCatalogCache: invalidated cache for '%s'", provider_id)

    def invalidate_all(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._entries.clear()
        log.debug("ModelCatalogCache: invalidated all caches")

    def refresh_async(self, provider_id: str) -> None:
        """Force a background refresh of *provider_id*.

        Unlike ``preload_async``, this always fetches even if the
        provider is already cached.
        """
        self.invalidate(provider_id)
        self.preload_async(provider_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_catalog(self):
        """Lazy-import and construct the ProviderCatalogService."""
        if self._catalog_factory is not None:
            return self._catalog_factory()
        from .provider_catalog import ProviderCatalogService
        return ProviderCatalogService()

    def _fetch_and_cache(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Fetch models synchronously, cache, and return.

        Deduplicates concurrent fetches: only the first caller performs
        the HTTP request; subsequent callers wait on a ``threading.Event``
        and receive the same result.
        """
        with self._lock:
            entry = self._entries.get(provider_id)
            if isinstance(entry, tuple):
                return entry
            if isinstance(entry, _FetchGate):
                # Another thread is already fetching — wait for it.
                gate = entry
                is_owner = False
            else:
                # First caller — create a gate and claim the fetch.
                gate = _FetchGate()
                self._entries[provider_id] = gate
                is_owner = True

        if is_owner:
            # Perform the actual fetch, then signal waiters.
            models = self._perform_fetch(provider_id)
            with self._lock:
                self._entries[provider_id] = models
            gate.result = models
            gate.event.set()
            return models
        else:
            # Wait for the in-flight fetch to complete.
            gate.event.wait()
            with self._lock:
                # After waiting, the entry should be the final result.
                final = self._entries.get(provider_id)
                if isinstance(final, tuple):
                    return final
                # Edge case: gate was invalidated during wait — fall
                # through and let the caller retry by recursing once.
                return self._fetch_and_cache(provider_id)

    def _perform_fetch(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
        """Actually perform the HTTP fetch (no locking — caller owns the gate)."""
        log.debug("ModelCatalogCache: fetching models for '%s'", provider_id)
        try:
            catalog = self._get_catalog()
            from ..config.settings import build_provider_config
            config = build_provider_config(provider_id)
            models = catalog.list_models(config)
        except Exception:
            log.exception(
                "ModelCatalogCache: failed to fetch models for '%s'",
                provider_id,
            )
            models = ()

        log.debug(
            "ModelCatalogCache: cached %d models for '%s'",
            len(models),
            provider_id,
        )
        return models

    def _preload_background(self) -> None:
        """Fetch models for all enabled providers (runs in a daemon thread).

        Uses ``_fetch_and_cache`` which handles deduplication — if a
        user-triggered fetch for the same provider is already in flight,
        the preload will wait for and reuse its result.
        """
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

    def _fetch_background(self, provider_id: str) -> None:
        """Fetch models in background, store result in cache.

        The ``_FetchGate`` was already registered by ``preload_async``
        or ``refresh_async``, so ``_fetch_and_cache`` will claim
        ownership and perform the actual HTTP call.
        """
        try:
            self._fetch_and_cache(provider_id)
        except Exception:
            log.exception(
                "ModelCatalogCache: background fetch failed for '%s'",
                provider_id,
            )
            # Store empty result so waiters are unblocked even on failure.
            with self._lock:
                entry = self._entries.get(provider_id)
                if isinstance(entry, _FetchGate):
                    entry.result = ()
                    entry.event.set()
                    self._entries[provider_id] = ()


# Singleton instance for the add-on lifecycle.
model_catalog_cache = ModelCatalogCache()
