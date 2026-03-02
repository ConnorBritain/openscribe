"""Runtime ASR model cache manager.

Keeps a small, bounded set of hot runtime model objects in memory so repeated
inference requests avoid cold model loads.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Tuple


class AsrRuntimeManager:
    """In-memory LRU caches for ASR runtime objects."""

    def __init__(self, *, cache_limit: int = 2, log_status: Callable[[str, str], None] | None = None):
        self._cache_limit = max(1, int(cache_limit))
        self._log_status = log_status
        self._lock = threading.RLock()
        self._caches: Dict[str, OrderedDict[str, Any]] = {
            "medasr": OrderedDict(),
            "parakeet": OrderedDict(),
            "voxtral": OrderedDict(),
            "whisper_transformers": OrderedDict(),
        }

    def get_or_create(self, family: str, key: str, factory: Callable[[], Any]) -> Tuple[Any, bool]:
        """Return (value, from_cache)."""
        if family not in self._caches:
            raise ValueError(f"Unknown runtime cache family: {family}")

        cache = self._caches[family]
        with self._lock:
            cached = cache.get(key)
            if cached is not None:
                cache.move_to_end(key)
                return cached, True

        created = factory()

        with self._lock:
            cache[key] = created
            cache.move_to_end(key)
            while len(cache) > self._cache_limit:
                evicted_key, _ = cache.popitem(last=False)
                if self._log_status:
                    self._log_status(
                        f"Evicted {family} runtime cache entry: {evicted_key}",
                        "grey",
                    )
        return created, False

    def peek(self, family: str, key: str) -> Any | None:
        """Get cached value if present, without creating."""
        if family not in self._caches:
            return None
        with self._lock:
            value = self._caches[family].get(key)
            if value is not None:
                self._caches[family].move_to_end(key)
            return value
