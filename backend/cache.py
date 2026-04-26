"""TTL cache — Redis varsa Redis, yoksa in-memory (geliştirme/tek worker).

Dışarıya aynı API'yi sunar: get / set / clear / age.
"""

from __future__ import annotations

import pickle
import threading
import time
from typing import Any, Optional

from .config import REDIS_URL

_redis_client = None

if REDIS_URL:
    try:
        import redis as _redis_mod
        _redis_client = _redis_mod.from_url(REDIS_URL)
        _redis_client.ping()
    except Exception:
        _redis_client = None


class TTLCache:
    """Tek arayüz; arka plan Redis veya in-memory dict."""

    def __init__(self, ttl_seconds: int = 600, name: str = "cache"):
        self.ttl = ttl_seconds
        self.name = name
        self._store: dict = {}
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        k = self._rk(key)
        if _redis_client is not None:
            try:
                raw = _redis_client.get(k)
                return pickle.loads(raw) if raw else None
            except Exception:
                pass
        return self._mem_get(key)

    def set(self, key: str, value: Any) -> None:
        k = self._rk(key)
        if _redis_client is not None:
            try:
                _redis_client.setex(k, self.ttl, pickle.dumps(value))
                return
            except Exception:
                pass
        self._mem_set(key, value)

    def age(self, key: str) -> Optional[int]:
        """Kalan saniye. Yok veya süresi geçmişse None."""
        k = self._rk(key)
        if _redis_client is not None:
            try:
                ttl = _redis_client.ttl(k)
                return int(ttl) if ttl > 0 else None
            except Exception:
                pass
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            _, expires_at = entry
            remaining = expires_at - time.time()
            return max(0, int(remaining)) if remaining > 0 else None

    def clear(self, key: Optional[str] = None) -> None:
        if _redis_client is not None:
            try:
                if key is None:
                    pattern = f"{self.name}:*"
                    keys = _redis_client.keys(pattern)
                    if keys:
                        _redis_client.delete(*keys)
                else:
                    _redis_client.delete(self._rk(key))
                return
            except Exception:
                pass
        with self._lock:
            if key is None:
                self._store.clear()
            else:
                self._store.pop(key, None)

    # ── Internals ──────────────────────────────────────────────────────────

    def _rk(self, key: str) -> str:
        return f"{self.name}:{key}"

    def _mem_get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                self._store.pop(key, None)
                return None
            return value

    def _mem_set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + self.ttl)


scan_cache        = TTLCache(ttl_seconds=600,  name="scan")
news_cache        = TTLCache(ttl_seconds=600,  name="news")
stock_cache       = TTLCache(ttl_seconds=300,  name="stock")
symbol_cache      = TTLCache(ttl_seconds=600,  name="sym")
stock_news_cache  = TTLCache(ttl_seconds=300,  name="snews")
exchange_cache    = TTLCache(ttl_seconds=300,  name="exch")
