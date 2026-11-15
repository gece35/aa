"""Süreç ve konteyner bellek ölçümü (Railway RAM üzerinden faturalandırır).

Yalnız Linux'ta veri döner (/proc ve cgroup dosyaları); Windows/macOS'ta ve
okunamayan alanlarda değer None olur. Hiçbir zaman istisna fırlatmaz.
"""

from __future__ import annotations

from typing import Dict, Optional

_MB = 1024 * 1024

# cgroup v2 ve v1 konteyner bellek kullanımı (Railway'in ölçtüğüne en yakın değer)
_CGROUP_FILES = (
    "/sys/fs/cgroup/memory.current",
    "/sys/fs/cgroup/memory/memory.usage_in_bytes",
)


def _read_status_kb(field: str) -> Optional[int]:
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _read_cgroup_bytes() -> Optional[int]:
    for path in _CGROUP_FILES:
        try:
            with open(path, encoding="ascii") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            continue
    return None


def memory_mb() -> Dict[str, Optional[float]]:
    """{'rss': şu anki süreç belleği, 'peak': süreç ömrü boyunca en yüksek,
    'container': konteynerin toplam belleği} — MB cinsinden, 1 ondalık."""
    rss = _read_status_kb("VmRSS")
    peak = _read_status_kb("VmHWM")
    cg = _read_cgroup_bytes()
    return {
        "rss": round(rss / 1024, 1) if rss is not None else None,
        "peak": round(peak / 1024, 1) if peak is not None else None,
        "container": round(cg / _MB, 1) if cg is not None else None,
    }
