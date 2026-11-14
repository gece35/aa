"""Günlük kota sayaçları — süreç belleğinde.

Uygulama tek süreç olarak çalıştığı için sayaçlar tutarlıdır; her deploy'da
sıfırlanırlar (kabul edilebilir: yalnızca kötüye kullanım freni).

Anahtar: quota:{subject}:{scope}:{YYYYMMDD}
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_memory: dict = {}
_MAX_KEYS = 20000


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _key(subject: str, scope: str) -> str:
    return f"quota:{subject}:{scope}:{_today()}"


def incr_and_get(subject: str, scope: str, per: str = "day") -> int:
    key = _key(subject, scope)
    with _lock:
        cur = _memory.get(key, 0) + 1
        _memory[key] = cur
        if len(_memory) > _MAX_KEYS:
            suffix = f":{_today()}"
            for k in [k for k in _memory if not k.endswith(suffix)]:
                _memory.pop(k, None)
            # Hâlâ taşıyorsa (aynı gün içinde çok fazla anahtar) en eskileri at
            while len(_memory) > _MAX_KEYS:
                _memory.pop(next(iter(_memory)))
        return cur


def get(subject: str, scope: str, per: str = "day") -> int:
    with _lock:
        return _memory.get(_key(subject, scope), 0)


def reset() -> None:
    """Testler için."""
    with _lock:
        _memory.clear()
