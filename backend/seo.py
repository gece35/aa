"""Arama motorları için sunucuda render edilen sayfalar.

  /hisse/<SEMBOL>   Her hisse için indekslenebilir özet sayfa (puan, fiyat,
                    gösterge özeti). Uygulamanın kendisi tek sayfalık (SPA)
                    olduğundan hisseler başka türlü indekslenemiyor.
  /hisseler         Tüm hisselerin pazar/sektöre göre dizini (iç linkleme).
  /sitemap.xml      Statik sayfalar + blog + yasal + hisse sayfaları.

Maliyet: sayfa verisi önce tarama önbelleğinden (symbol_cache) alınır; yoksa tek
hisselik indirme yapılıp 6 saat saklanır — bot trafiği en kötü durumda hisse
başına günde ~4 küçük indirme üretir. Üyelere özel içerik (giriş sinyali, SL/TP,
formasyonlar, bilanço analizi) bu sayfalarda bilinçli olarak gösterilmez.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timezone
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, abort, redirect, render_template

from .cache import TTLCache, symbol_cache
from .config import SITE_URL
from .sectors import get_sector, sector_label
from .security import limiter
from .tickers import MARKETS, get_tickers, market_of_symbol, resolve_symbol, strip_suffix

logger = logging.getLogger(__name__)

seo_bp = Blueprint("seo", __name__)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

_SNAPSHOT_TTL = 6 * 3600
_MISS_TTL = 15 * 60
seo_cache = TTLCache(ttl_seconds=_SNAPSHOT_TTL, name="seo", max_entries=500)
_fetch_lock = threading.Lock()

MARKET_LABELS = {"bist": "BIST", "us": "ABD"}
_CURRENCY_SIGN = {"TRY": "₺", "USD": "$"}

# Sitemap'teki sabit sayfalar: (yol, changefreq, priority, kaynak dosya)
_STATIC_PAGES = [
    ("/", "daily", "1.0", "index.html"),
    ("/hisseler", "daily", "0.9", None),
    ("/rehber", "monthly", "0.8", "rehber.html"),
    ("/about", "monthly", "0.7", "about.html"),
    ("/faq", "monthly", "0.7", "faq.html"),
    ("/blog/", "weekly", "0.8", os.path.join("blog", "index.html")),
]


def site_url(path: str = "") -> str:
    return SITE_URL + path


def slug_for(symbol: str) -> str:
    """Hisse sayfası adresi: BIST'te `.IS` eki olmadan (THYAO.IS → THYAO)."""
    return strip_suffix(symbol)


# ── Biçimlendirme (Türkçe sayı biçimi) ───────────────────────────────────────

def _tr_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_price(value: Optional[float], currency: str) -> str:
    if value is None:
        return "—"
    return f"{_CURRENCY_SIGN.get(currency, '')}{_tr_number(value)}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"%{sign}{_tr_number(value)}"


# ── Veri ─────────────────────────────────────────────────────────────────────

def public_snapshot(symbol: str) -> Optional[dict]:
    """Hissenin herkese açık özet verisi (tarama satırıyla aynı sözlük) ya da None."""
    cached = symbol_cache.get(f"sym:{symbol}") or seo_cache.get(symbol)
    if cached is not None:
        return cached
    if seo_cache.get(f"miss:{symbol}"):
        return None

    with _fetch_lock:  # aynı anda tek indirme: bot dalgası yfinance'i boğmasın
        cached = symbol_cache.get(f"sym:{symbol}") or seo_cache.get(symbol)
        if cached is not None:
            return cached
        if seo_cache.get(f"miss:{symbol}"):
            return None
        try:
            from .data_fetcher import download_ohlcv
            from .scanner import get_index_df
            from .scoring import compute_regime_ok, score_symbol

            market = market_of_symbol(symbol)
            df = download_ohlcv([symbol], period="300d", interval="1d").get(symbol)
            result = None
            if df is not None and not df.empty:
                index_df = get_index_df(market)
                result = score_symbol(symbol, df, index_df, market, compute_regime_ok(index_df))
        except Exception:
            logger.exception("seo: %s özeti üretilemedi", symbol)
            result = None

        if result is None:
            seo_cache.set(f"miss:{symbol}", True, ttl=_MISS_TTL)
            return None
        snapshot = result.to_dict()
        snapshot["sector"] = get_sector(symbol)
        seo_cache.set(symbol, snapshot)
        return snapshot


def _related(symbol: str, market: str, sector: str, limit: int = 10) -> List[dict]:
    out = []
    for other in get_tickers(market):
        if other != symbol and get_sector(other) == sector:
            out.append({"slug": slug_for(other), "name": slug_for(other)})
            if len(out) >= limit:
                break
    return out


def _score_comment(score: int) -> str:
    if score >= 9:
        return "çok güçlü bir teknik görünüme"
    if score >= 7:
        return "olumlu bir teknik görünüme"
    if score >= 5:
        return "nötr-olumlu bir teknik görünüme"
    if score >= 3:
        return "zayıf bir teknik görünüme"
    return "olumsuz bir teknik görünüme"


def _page_context(symbol: str, snap: Optional[dict]) -> Dict:
    market = market_of_symbol(symbol)
    currency = MARKETS[market]["currency"]
    name = slug_for(symbol)
    sector = get_sector(symbol)
    ctx: Dict = {
        "symbol": symbol,
        "name": name,
        "market": market,
        "market_label": MARKET_LABELS.get(market, market.upper()),
        "sector_label": sector_label(sector),
        "related": _related(symbol, market, sector),
        "canonical": site_url(f"/hisse/{name}"),
        "app_url": site_url(f"/?s={symbol}"),
        "home_url": site_url("/"),
        "index_url": site_url("/hisseler"),
        "available": snap is not None,
        "year": date.today().year,
    }
    if snap is None:
        ctx["title"] = f"{name} Hisse Teknik Analiz ve Puanı ({ctx['market_label']}) | Nebula Scanner"
        ctx["description"] = (f"{name} hissesi için teknik analiz puanı, gösterge özeti ve fiyat "
                              f"bilgileri Nebula Scanner'da.")
        return ctx

    score = int(snap.get("score") or 0)
    indicators = []
    for ind in snap.get("indicators") or []:
        sc = float(ind.get("score") or 0)
        indicators.append({
            "name": ind.get("name") or "",
            "detail": ind.get("detail") or "",
            "state": "olumlu" if sc > 0 else ("riskli" if sc < 0 else "nötr"),
            "css": "on" if sc > 0 else ("penalty" if sc < 0 else "off"),
        })

    ctx.update({
        "score": score,
        "score_comment": _score_comment(score),
        "price": _fmt_price(snap.get("price"), currency),
        "change_day": _fmt_pct(snap.get("change_pct")),
        "change_week": _fmt_pct(snap.get("change_week_pct")),
        "change_month": _fmt_pct(snap.get("change_month_pct")),
        "day_up": (snap.get("change_pct") or 0) >= 0,
        "week_up": (snap.get("change_week_pct") or 0) >= 0,
        "month_up": (snap.get("change_month_pct") or 0) >= 0,
        "high_52w": _fmt_price(snap.get("high_52w"), currency),
        "low_52w": _fmt_price(snap.get("low_52w"), currency),
        "indicators": indicators,
        "volume_spike": bool(snap.get("volume_spike")),
        "near_peak": bool(snap.get("near_peak")),
        "updated": datetime.now(timezone.utc).strftime("%d.%m.%Y"),
    })
    ctx["title"] = f"{name} Hisse Teknik Analiz: {score}/10 Puan ({ctx['market_label']}) | Nebula Scanner"
    ctx["description"] = (
        f"{name} hissesi teknik analiz puanı {score}/10. Son fiyat {ctx['price']}, günlük "
        f"{ctx['change_day']}, haftalık {ctx['change_week']}. EMA, RSI, MACD, Bollinger ve ADX "
        f"göstergelerinin güncel özeti."
    )
    ctx["json_ld"] = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": ctx["canonical"],
                "url": ctx["canonical"],
                "name": ctx["title"],
                "description": ctx["description"],
                "inLanguage": "tr",
                "isPartOf": {"@id": site_url("/#webapp")},
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Nebula Scanner", "item": ctx["home_url"]},
                    {"@type": "ListItem", "position": 2, "name": "Hisseler", "item": ctx["index_url"]},
                    {"@type": "ListItem", "position": 3, "name": name, "item": ctx["canonical"]},
                ],
            },
        ],
    }
    return ctx


# ── Rotalar ──────────────────────────────────────────────────────────────────

@seo_bp.route("/hisse/<symbol>")
@limiter.limit("120 per hour")
def stock_page(symbol: str):
    resolved = resolve_symbol(symbol)
    if resolved is None:
        abort(404)
    canonical_slug = slug_for(resolved)
    if symbol != canonical_slug:
        # /hisse/thyao, /hisse/THYAO.IS → tek (kanonik) adres
        return redirect(f"/hisse/{canonical_slug}", code=301)

    snap = public_snapshot(resolved)
    ctx = _page_context(resolved, snap)
    if snap is None:
        resp = Response(render_template("hisse.html", **ctx), status=503, mimetype="text/html")
        resp.headers["Retry-After"] = "3600"
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
    resp = Response(render_template("hisse.html", **ctx), mimetype="text/html")
    resp.headers["Cache-Control"] = "public, max-age=1800"
    return resp


@seo_bp.route("/hisseler")
def stock_index():
    groups = []
    for market in ("bist", "us"):
        by_sector: Dict[str, List[dict]] = {}
        for sym in get_tickers(market):
            by_sector.setdefault(get_sector(sym), []).append({"slug": slug_for(sym), "name": slug_for(sym)})
        sectors = [
            {"label": sector_label(key), "stocks": sorted(stocks, key=lambda s: s["name"])}
            for key, stocks in by_sector.items()
        ]
        sectors.sort(key=lambda s: s["label"])
        groups.append({
            "label": "Borsa İstanbul (BIST)" if market == "bist" else "ABD Borsaları",
            "count": len(get_tickers(market)),
            "sectors": sectors,
        })
    resp = Response(render_template(
        "hisseler.html", groups=groups, canonical=site_url("/hisseler"),
        home_url=site_url("/"), year=date.today().year,
        total=sum(g["count"] for g in groups),
    ), mimetype="text/html")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def _file_lastmod(*parts: str) -> Optional[str]:
    try:
        ts = os.path.getmtime(os.path.join(FRONTEND_DIR, *parts))
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return None


def _html_slugs(subdir: str) -> List[str]:
    try:
        names = os.listdir(os.path.join(FRONTEND_DIR, subdir))
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".html") and n != "index.html")


@seo_bp.route("/sitemap.xml")
def sitemap():
    today = date.today().isoformat()
    entries = []  # (loc, lastmod, changefreq, priority)
    for path, freq, prio, source in _STATIC_PAGES:
        lastmod = _file_lastmod(source) if source else today
        entries.append((site_url(path), lastmod, freq, prio))
    for slug in _html_slugs("blog"):
        entries.append((site_url(f"/blog/{slug}"), _file_lastmod("blog", f"{slug}.html"), "monthly", "0.7"))
    for slug in _html_slugs("legal"):
        entries.append((site_url(f"/legal/{slug}"), _file_lastmod("legal", f"{slug}.html"), "yearly", "0.3"))
    for market in ("bist", "us"):
        for sym in get_tickers(market):
            entries.append((site_url(f"/hisse/{slug_for(sym)}"), today, "daily", "0.6"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, prio in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{xml_escape(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{prio}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    resp = Response("\n".join(lines) + "\n", mimetype="application/xml")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp
