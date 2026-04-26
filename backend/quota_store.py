"""Günlük kota sayaçları — Redis varsa Redis, yoksa in-memory dict.

Anahtar: quota:{user_id}:{scope}:{YYYYMMDD}
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .config import REDIS_URL

_redis = None
_lock = threading.Lock()
_memory: dict = {}

if REDIS_URL:
    try:
        import redis
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
    except Exception:
        _redis = None


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _ttl_until_tomorrow_seconds() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return int((tomorrow - now).total_seconds()) + 60


def incr_and_get(user_id: str, scope: str, per: str = "day") -> int:
    bucket = _today()
    key = f"quota:{user_id}:{scope}:{bucket}"
    if _redis is not None:
        try:
            new_val = _redis.incr(key)
            if new_val == 1:
                _redis.expire(key, _ttl_until_tomorrow_seconds())
            return int(new_val)
        except Exception:
            pass
    with _lock:
        cur = _memory.get(key, 0) + 1
        _memory[key] = cur
        # crude memory cleanup — günde bir
        if len(_memory) > 10000:
            cutoff = _today()
            for k in list(_memory.keys()):
                if not k.endswith(cutoff):
                    _memory.pop(k, None)
        return cur


def get(user_id: str, scope: str, per: str = "day") -> int:
    bucket = _today()
    key = f"quota:{user_id}:{scope}:{bucket}"
    if _redis is not None:
        try:
            v = _redis.get(key)
            return int(v) if v else 0
        except Exception:
            pass
    with _lock:
        return _memory.get(key, 0)
