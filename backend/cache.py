"""Süreç içi TTL + LRU önbellek.

Uygulama tek gunicorn süreci (thread'li) olarak çalışır; bu yüzden önbellek
süreç belleğinde tutulur ve Redis'e gerek yoktur. Her önbelleğin bir kayıt
üst sınırı vardır: sınır aşılınca önce süresi dolanlar, sonra en eski
kullanılanlar atılır — bellek süresiz büyümez.

Önbelleğe konan değerler REFERANS olarak saklanır: okuyan taraf dönen
nesneyi yerinde değiştirmemeli, gerekiyorsa kopyalamalıdır.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int = 600, name: str = "cache", max_entries: int = 512):
        self.ttl = ttl_seconds
        self.name = name
        self.max_entries = max(1, int(max_entries))
        self._store: "OrderedDict[str, tuple]" = OrderedDict()
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Değeri saklar. `ttl` verilirse bu kayıt için varsayılan ömrü ezer."""
        lifetime = self.ttl if ttl is None else max(1, int(ttl))
        now = time.time()
        with self._lock:
            self._store[key] = (value, now + lifetime)
            self._store.move_to_end(key)
            if len(self._store) > self.max_entries:
                self._evict(now)

    def age(self, key: str) -> Optional[int]:
        """Kalan saniye. Yok veya süresi geçmişse None."""
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            remaining = entry[1] - time.time()
            return int(remaining) if remaining > 0 else None

    def clear(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._store.clear()
            else:
                self._store.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ── Internals ──────────────────────────────────────────────────────────

    def _evict(self, now: float) -> None:
        """Kilit altında çağrılır: önce süresi dolanları, sonra LRU'yu at."""
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            self._store.pop(k, None)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)


# Üst sınırlar kayıt boyutuna göre seçildi: stock detayı (500 OHLCV satırı)
# büyük, tarama satırı (sym) küçüktür.
scan_cache         = TTLCache(ttl_seconds=600,   name="scan",  max_entries=8)
news_cache         = TTLCache(ttl_seconds=600,   name="news",  max_entries=8)
stock_cache        = TTLCache(ttl_seconds=300,   name="stock", max_entries=100)
symbol_cache       = TTLCache(ttl_seconds=600,   name="sym",   max_entries=1000)
stock_news_cache   = TTLCache(ttl_seconds=300,   name="snews", max_entries=200)
exchange_cache     = TTLCache(ttl_seconds=300,   name="exch",  max_entries=8)
fundamentals_cache = TTLCache(ttl_seconds=86400, name="fund",  max_entries=500)  # bilanço çeyreklik güncellenir
analysis_cache     = TTLCache(ttl_seconds=6 * 3600, name="analysis", max_entries=8)  # admin backtest / sinyal etüdü
