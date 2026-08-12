"""AI destekli bilanço / temel analiz — yfinance + Groq (Llama 3.3).

Bir hissenin son bilanço ve gelir tablosu verisini yfinance'ten çeker, temel
oranları hesaplar ve Groq LLM ile finansal sağlığı 'positive' / 'neutral' /
'negative' olarak sınıflandırır.

yfinance temel verisi ABD hisselerinde güvenilir, BIST (.IS) hisselerinde çoğu
zaman boş gelir. Veri yoksa {"available": False} döner ve frontend zarif bir
fallback mesajı gösterir.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Şirketler genelde çeyreklik bilanço açıklar (çeyrek sonundan ~1-2 ay sonra).
# En son bilanço döneminin üzerinden bu kadar ay geçmişse veri "eski" sayılır
# ve frontend'de uyarı rozeti gösterilir (analiz yine de yapılır/gösterilir).
STALE_THRESHOLD_MONTHS = 6

# yfinance kalem adları sürümden sürüme / hisseden hisseye değişebildiği için
# her metrik için birden fazla olası satır adı (alias) deniyoruz.
_BALANCE_ALIASES: Dict[str, List[str]] = {
    "total_assets": ["Total Assets"],
    "total_liabilities": [
        "Total Liabilities Net Minority Interest",
        "Total Liabilities",
    ],
    "equity": [
        "Stockholders Equity",
        "Total Stockholder Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ],
    "total_debt": ["Total Debt"],
    "cash": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
}

_INCOME_ALIASES: Dict[str, List[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Operating Income Or Loss"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
}


def _pick(df: Optional[pd.DataFrame], aliases: List[str], col_idx: int = 0) -> Optional[float]:
    """DataFrame'in `col_idx`. kolonundan alias'lardan ilk bulunan satırı döner."""
    if df is None or df.empty or col_idx >= df.shape[1]:
        return None
    for name in aliases:
        if name in df.index:
            try:
                val = df.iloc[:, col_idx].loc[name]
                if val is None or pd.isna(val):
                    continue
                return float(val)
            except (KeyError, TypeError, ValueError):
                continue
    return None


def _safe_ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _yoy_pct(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100.0


def _period_staleness(period: Optional[str]):
    """Bilanço döneminin bugüne göre kaç ay eski olduğunu ve eşiği aşıp
    aşmadığını döner. Tarih ayrıştırılamazsa (None, None) döner."""
    if not period:
        return None, None
    try:
        period_date = datetime.strptime(period[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None, None
    now = datetime.now(timezone.utc)
    months = (now.year - period_date.year) * 12 + (now.month - period_date.month)
    if now.day < period_date.day:
        months -= 1
    months = max(months, 0)
    return months, months >= STALE_THRESHOLD_MONTHS


def fetch_fundamentals(symbol: str) -> Optional[Dict]:
    """Hissenin son bilanço + gelir tablosu metriklerini döner. Veri yoksa None."""
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return None

    try:
        ticker = yf.Ticker(symbol)
        balance = ticker.balance_sheet
        income = ticker.income_stmt
        # Yıllık boşsa çeyreklik veriye düş
        if balance is None or balance.empty:
            balance = ticker.quarterly_balance_sheet
        if income is None or income.empty:
            income = ticker.quarterly_income_stmt
    except Exception as exc:
        logger.warning("Temel veri çekilemedi %s: %s", symbol, exc)
        return None

    if (balance is None or balance.empty) and (income is None or income.empty):
        return None

    # Bilanço (en yeni kolon = 0)
    total_assets = _pick(balance, _BALANCE_ALIASES["total_assets"])
    total_liabilities = _pick(balance, _BALANCE_ALIASES["total_liabilities"])
    equity = _pick(balance, _BALANCE_ALIASES["equity"])
    total_debt = _pick(balance, _BALANCE_ALIASES["total_debt"])
    cash = _pick(balance, _BALANCE_ALIASES["cash"])
    current_assets = _pick(balance, _BALANCE_ALIASES["current_assets"])
    current_liabilities = _pick(balance, _BALANCE_ALIASES["current_liabilities"])

    # Gelir tablosu — en yeni (0) ve bir önceki dönem (1) YoY için
    revenue = _pick(income, _INCOME_ALIASES["revenue"], 0)
    revenue_prev = _pick(income, _INCOME_ALIASES["revenue"], 1)
    gross_profit = _pick(income, _INCOME_ALIASES["gross_profit"], 0)
    operating_income = _pick(income, _INCOME_ALIASES["operating_income"], 0)
    net_income = _pick(income, _INCOME_ALIASES["net_income"], 0)
    net_income_prev = _pick(income, _INCOME_ALIASES["net_income"], 1)

    # Hiç anlamlı veri yoksa fallback sinyali
    core_values = [total_assets, equity, revenue, net_income]
    if all(v is None for v in core_values):
        return None

    period = None
    try:
        src = balance if (balance is not None and not balance.empty) else income
        if src is not None and not src.empty:
            period = str(src.columns[0])[:10]
    except Exception:
        period = None

    period_age_months, is_stale = _period_staleness(period)

    metrics = {
        "period": period,
        "period_age_months": period_age_months,
        "is_stale": is_stale,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "equity": equity,
        "total_debt": total_debt,
        "cash": cash,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        # Türetilmiş oranlar
        "debt_to_equity": _safe_ratio(total_debt, equity),
        "current_ratio": _safe_ratio(current_assets, current_liabilities),
        "net_margin_pct": (
            _safe_ratio(net_income, revenue) * 100.0
            if _safe_ratio(net_income, revenue) is not None else None
        ),
        "revenue_yoy_pct": _yoy_pct(revenue, revenue_prev),
        "net_income_yoy_pct": _yoy_pct(net_income, net_income_prev),
    }
    return metrics


def _fmt(val: Optional[float], suffix: str = "") -> str:
    if val is None:
        return "veri yok"
    if abs(val) >= 1e9:
        return f"{val / 1e9:.2f}B{suffix}"
    if abs(val) >= 1e6:
        return f"{val / 1e6:.2f}M{suffix}"
    return f"{val:.2f}{suffix}"


def _build_prompt(symbol: str, m: Dict) -> str:
    lines = [
        f"Hisse: {symbol}",
        f"Dönem: {m.get('period') or 'bilinmiyor'}",
        "",
        "Bilanço:",
        f"- Toplam Varlık: {_fmt(m['total_assets'])}",
        f"- Toplam Yükümlülük: {_fmt(m['total_liabilities'])}",
        f"- Özkaynak: {_fmt(m['equity'])}",
        f"- Toplam Borç: {_fmt(m['total_debt'])}",
        f"- Nakit: {_fmt(m['cash'])}",
        "",
        "Gelir Tablosu:",
        f"- Hasılat: {_fmt(m['revenue'])}",
        f"- Brüt Kar: {_fmt(m['gross_profit'])}",
        f"- Faaliyet Karı: {_fmt(m['operating_income'])}",
        f"- Net Kar: {_fmt(m['net_income'])}",
        "",
        "Oranlar:",
        f"- Borç/Özkaynak: {_fmt(m['debt_to_equity'])}",
        f"- Cari Oran: {_fmt(m['current_ratio'])}",
        f"- Net Kar Marjı: {_fmt(m['net_margin_pct'], '%')}",
        f"- Hasılat YoY: {_fmt(m['revenue_yoy_pct'], '%')}",
        f"- Net Kar YoY: {_fmt(m['net_income_yoy_pct'], '%')}",
    ]
    return "\n".join(lines)


_SYSTEM_PROMPT = """Sen deneyimli bir finansal analiz asistanısın. Sana verilen bir
hissenin bilanço ve gelir tablosu metriklerini değerlendirirsin.

Kurallar:
- Türkçe, kısa ve net yaz. Teknik jargonu sadeleştir.
- YATIRIM TAVSİYESİ VERME. Sadece bilançonun finansal sağlığını değerlendir.
- Borçluluk, karlılık, büyüme ve likidite açısından bak.
- Sonucu yalnızca şu JSON formatında döndür (başka metin ekleme):
{
  "verdict": "positive" | "neutral" | "negative",
  "summary": "2-3 cümlelik Türkçe özet",
  "strengths": ["güçlü yön 1", "güçlü yön 2"],
  "risks": ["risk 1", "risk 2"]
}
- verdict: finansal görünüm genel olarak sağlıklı/güçlüyse "positive",
  karışık/belirsizse "neutral", zayıf/riskliyse "negative" olmalı.
- strengths ve risks en fazla 3'er madde, kısa cümleler.
"""


def analyze_fundamentals(symbol: str) -> Dict:
    """Bilanço metriklerini çeker ve Groq ile sınıflandırır."""
    symbol = (symbol or "").upper().strip()
    metrics = fetch_fundamentals(symbol)
    if metrics is None:
        return {"available": False, "symbol": symbol}

    if not GROQ_API_KEY:
        return {"available": False, "symbol": symbol, "error": "config_error"}

    user_prompt = _build_prompt(symbol, metrics)

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=700,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception:
        logger.exception("Groq bilanço analizi hatası %s", symbol)
        return {"available": False, "symbol": symbol, "error": "ai_error"}

    verdict = str(parsed.get("verdict", "")).lower().strip()
    if verdict not in ("positive", "neutral", "negative"):
        verdict = "neutral"

    def _str_list(val) -> List[str]:
        if not isinstance(val, list):
            return []
        return [str(x)[:200] for x in val if str(x).strip()][:3]

    return {
        "available": True,
        "symbol": symbol,
        "verdict": verdict,
        "summary": str(parsed.get("summary", ""))[:600],
        "strengths": _str_list(parsed.get("strengths")),
        "risks": _str_list(parsed.get("risks")),
        "metrics": metrics,
    }
