"""Desteklenen pazarlardaki hisse sembollerinin listesi.

BIST sembolleri yfinance formatinda ``.IS`` uzantisiyla tutulur.
US sembolleri ham sekilde (AAPL, MSFT, ...) tutulur.
"""

BIST_TICKERS = [
    "AKBNK.IS", "GARAN.IS", "ISCTR.IS", "YKBNK.IS", "HALKB.IS", "VAKBN.IS",
    "THYAO.IS", "PGSUS.IS", "TAVHL.IS",
    "ASELS.IS", "OTKAR.IS", "KOC.IS", "SAHOL.IS", "ENKAI.IS", "KCHOL.IS",
    "TUPRS.IS", "PETKM.IS", "EREGL.IS", "KRDMD.IS", "SISE.IS",
    "ARCLK.IS", "VESTL.IS", "TOASO.IS", "FROTO.IS", "TTRAK.IS",
    "BIMAS.IS", "MGROS.IS", "SOKM.IS", "CCOLA.IS", "AEFES.IS", "ULKER.IS",
    "TCELL.IS", "TTKOM.IS",
    "EKGYO.IS", "ISGYO.IS", "TRGYO.IS",
    "ENJSA.IS", "AKSEN.IS", "ZOREN.IS", "AYGAZ.IS",
    "KOZAL.IS", "KOZAA.IS", "IPEKE.IS",
    "SASA.IS", "HEKTS.IS", "KORDS.IS", "TKFEN.IS",
    "MAVI.IS", "LOGO.IS", "NETAS.IS", "KAREL.IS",
]

US_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "ORCL", "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN",
    "NFLX", "DIS", "CMCSA", "T", "VZ",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK",
    "V", "MA", "PYPL", "SQ",
    "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "KO", "PEP",
    "PG", "CL", "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH",
    "XOM", "CVX", "COP",
    "BA", "CAT", "GE", "HON", "LMT", "RTX", "DE",
    "F", "GM",
]

MARKETS = {
    "bist": {
        "code": "bist",
        "label": "Borsa Istanbul",
        "flag": "TR",
        "currency": "TRY",
        "tickers": BIST_TICKERS,
    },
    "us": {
        "code": "us",
        "label": "US Stocks",
        "flag": "US",
        "currency": "USD",
        "tickers": US_TICKERS,
    },
}


def get_tickers(market: str):
    market = (market or "").lower()
    if market not in MARKETS:
        return []
    return list(MARKETS[market]["tickers"])


def strip_suffix(symbol: str) -> str:
    return symbol.replace(".IS", "")
