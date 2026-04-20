"""yfinance uzerinden toplu OHLCV veri indirme.

Buyuk ticker listelerinde yfinance'in tek seferlik `download` cagrisi
429 rate-limit ve timeout problemlerine yol acabiliyor. Bu yuzden
listeyi 25'lik chunk'lara boluyor, 3 paralel worker kullanıyor
ve eksik ticker'lar icin otomatik retry (en fazla 3 deneme) uyguluyor.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CHUNK_SIZE = 25
MAX_PARALLEL_CHUNKS = 3
MAX_RETRIES = 3


def download_ohlcv(tickers: List[str], period: str = "200d", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    """Verilen tum tickerlarin OHLCV verisini paralel chunk'lar halinde indirir."""
    if not tickers:
        return {}

    tickers = list(dict.fromkeys(tickers))  # dedupe, preserve order

    if len(tickers) <= CHUNK_SIZE:
        return _download_chunk_with_retry(tickers, period, interval)

    chunks = [tickers[i : i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]
    logger.info(
        "Downloading %d tickers across %d chunks (period=%s)",
        len(tickers), len(chunks), period,
    )

    out: Dict[str, pd.DataFrame] = {}
    workers = min(MAX_PARALLEL_CHUNKS, len(chunks))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_chunk_with_retry, c, period, interval): c for c in chunks}
        for fut in as_completed(futures):
            try:
                out.update(fut.result())
            except Exception:
                logger.exception("Chunk indirme hatasi")
    return out


def _download_chunk_with_retry(tickers: List[str], period: str, interval: str) -> Dict[str, pd.DataFrame]:
    """Chunk indirmesini retry ile dener; her denemede eksik kalanlar tekrar istenir."""
    accumulated: Dict[str, pd.DataFrame] = {}
    remaining = list(tickers)

    for attempt in range(MAX_RETRIES):
        if not remaining:
            break
        batch = _download_chunk(remaining, period, interval)
        accumulated.update(batch)
        remaining = [t for t in remaining if t not in accumulated]
        if not remaining:
            break
        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt  # 1s, 2s
            logger.warning(
                "Attempt %d: %d/%d ticker eksik, %ds bekliyor",
                attempt + 1, len(remaining), len(tickers), wait,
            )
            time.sleep(wait)
        else:
            # Son denemede her birini teker teker dene
            logger.warning("Son deneme: %d ticker teker teker indiriliyor", len(remaining))
            for sym in remaining:
                single = _download_chunk([sym], period, interval)
                accumulated.update(single)
                time.sleep(0.4)

    return accumulated


def fetch_exchange_rate(base: str = "TRY=X") -> float | None:
    """USD/TRY kurunu döner (1 USD = X TRY). Hata durumunda None."""
    try:
        raw = yf.download(base, period="5d", interval="1d", progress=False, auto_adjust=False)
        if raw is None or raw.empty:
            return None
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        val = float(close.dropna().iloc[-1])
        return val if val > 0 else None
    except Exception as exc:
        logger.warning("Kur cekilemedi (%s): %s", base, exc)
        return None


def _download_chunk(tickers: List[str], period: str, interval: str) -> Dict[str, pd.DataFrame]:
    if not tickers:
        return {}

    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Toplu indirme basarisiz: %s", exc)
        return {}

    out: Dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out

    if len(tickers) == 1:
        symbol = tickers[0]
        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            try:
                df = df[symbol].copy()
            except KeyError:
                df.columns = df.columns.get_level_values(-1)
        df = _normalize(df)
        if df is not None and not df.empty:
            out[symbol] = df
        return out

    level0 = set(raw.columns.get_level_values(0))
    for symbol in tickers:
        if symbol not in level0:
            continue
        try:
            df = raw[symbol].copy()
            df = _normalize(df)
            if df is None or df.empty:
                continue
            out[symbol] = df
        except Exception:
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
