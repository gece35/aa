"""yfinance uzerinden toplu OHLCV veri indirme."""

from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def download_ohlcv(tickers: List[str], period: str = "200d", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    """Verilen tum tickerlarin OHLCV verisini tek seferde indirir.

    yfinance.download cok-thread destekli oldugundan tum hisseler paralel cekilir.
    Donen sozlukte anahtar sembol, deger ise o sembolun dataframe'idir.
    """
    if not tickers:
        return {}

    logger.info("Downloading %d tickers (period=%s)", len(tickers), period)

    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # pragma: no cover - aglama kodu
        logger.exception("Toplu indirme basarisiz: %s", exc)
        return {}

    out: Dict[str, pd.DataFrame] = {}

    if raw is None or raw.empty:
        return out

    if len(tickers) == 1:
        symbol = tickers[0]
        df = _normalize(raw)
        if df is not None and not df.empty:
            out[symbol] = df
        return out

    for symbol in tickers:
        try:
            if (symbol,) in raw.columns or symbol in raw.columns.get_level_values(0):
                df = raw[symbol].copy()
            else:
                continue
            df = _normalize(df)
            if df is None or df.empty:
                continue
            out[symbol] = df
        except Exception:  # pragma: no cover
            logger.debug("%s icin veri cikartilamadi", symbol)
            continue

    return out


def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.dropna(how="all")
    if df.empty:
        return None
    df.columns = [str(c).capitalize() for c in df.columns]
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        return None
    if "Volume" not in df.columns:
        df["Volume"] = 0
    return df
