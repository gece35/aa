"""Pazar seans saatleri — zamanlayıcı ve önbellek TTL'leri için.

Veri günlük bar olduğundan pazar kapalıyken fiyat değişmez; bu modül
"şu an işlem var mı?" sorusunu yanıtlar ki kapalı saatlerde yfinance'e
gidilmesin ve önbellek bir sonraki açılışa kadar yaşasın.

Resmî tatiller bilinçli olarak modellenmez: tatilde pazar "açık" sayılır,
sonuç yalnızca birkaç gereksiz (ucuz) kontroldür.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _TZ_IST = ZoneInfo("Europe/Istanbul")
    _TZ_NY = ZoneInfo("America/New_York")
except Exception:  # tzdata yoksa sabit ofsetlere düş (NY yaz saatinde 1 saat kayar)
    _TZ_IST = timezone(timedelta(hours=3))
    _TZ_NY = timezone(timedelta(hours=-5))

# (saat dilimi, açılış, kapanış). Kapanışa ~20 dk eklenmiştir: yfinance
# gecikmeli veri verdiği için son barın oturması kapanıştan biraz sonra olur.
_SESSIONS = {
    "bist": (_TZ_IST, dtime(10, 0), dtime(18, 30)),
    "us": (_TZ_NY, dtime(9, 30), dtime(16, 20)),
}

MARKET_CODES = tuple(_SESSIONS.keys())


def _now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def is_market_open(market: str, now: Optional[datetime] = None) -> bool:
    """Pazar şu an (gecikme payı dahil) seansta mı? Bilinmeyen pazar → True."""
    session = _SESSIONS.get((market or "").lower())
    if session is None:
        return True
    tz, open_t, close_t = session
    local = _now(now).astimezone(tz)
    if local.weekday() >= 5:
        return False
    return open_t <= local.time() < close_t


def any_market_open(now: Optional[datetime] = None) -> bool:
    return any(is_market_open(m, now) for m in _SESSIONS)


def seconds_until_next_open(market: str, now: Optional[datetime] = None) -> int:
    """Bir sonraki seans açılışına kalan saniye. Pazar açıksa 0."""
    session = _SESSIONS.get((market or "").lower())
    if session is None:
        return 0
    if is_market_open(market, now):
        return 0
    tz, open_t, _close_t = session
    local = _now(now).astimezone(tz)
    candidate = local.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return max(0, int((candidate - local).total_seconds()))


def cache_ttl(market: str, open_ttl: int, closed_cap: int = 6 * 3600,
              now: Optional[datetime] = None) -> int:
    """Önbellek ömrü: seanstayken `open_ttl`, kapalıyken bir sonraki açılışa
    kadar (en fazla `closed_cap`, en az `open_ttl`)."""
    if is_market_open(market, now):
        return int(open_ttl)
    remaining = seconds_until_next_open(market, now)
    return int(max(open_ttl, min(closed_cap, remaining)))
