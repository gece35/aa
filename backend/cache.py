"""Basit thread-safe in-memory TTL cache."""

import threading
import time


class TTLCache:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key, value):
        with self._lock:
            self._store[key] = (value, time.time() + self.ttl)

    def age(self, key):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            _, expires_at = entry
            remaining = expires_at - time.time()
            return max(0, int(remaining))

    def clear(self, key=None):
        with self._lock:
            if key is None:
                self._store.clear()
            else:
                self._store.pop(key, None)


scan_cache = TTLCache(ttl_seconds=600)
news_cache = TTLCache(ttl_seconds=600)
stock_cache = TTLCache(ttl_seconds=300)
symbol_cache = TTLCache(ttl_seconds=600)
stock_news_cache = TTLCache(ttl_seconds=300)
exchange_cache = TTLCache(ttl_seconds=300)
