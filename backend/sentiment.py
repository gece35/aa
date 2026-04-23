"""Basit, hizli, lexicon tabanli sentiment skorlama.

Baglimsizik gerektirmez; baslik + ozet icindeki pozitif/negatif anahtar
kelimelerin farkina gore 'positive' / 'neutral' / 'negative' donduruyoruz.
TR ve EN kelime listesi birlikte kullanilir, piyasa haberleri icin yeterli
dogruluk saglar.
"""

from __future__ import annotations

import re
from typing import Tuple

_POS_WORDS = {
    # TR
    "yukseldi", "yukselis", "artti", "artis", "rekor", "kazanc", "kazandi",
    "kar", "kari", "karli", "basari", "basarili", "guclendi", "guclu",
    "talep", "genisleme", "yatirim", "anlasma", "ihracat", "buyume", "buyudu",
    "ralli", "pozitif", "olumlu", "toparlandi", "toparlanma", "firladi",
    "destek", "onayladi", "onay", "imzaladi", "acildi", "hedef", "beklenti",
    "uretim", "genisletti", "sozlesme", "tesvik", "indirim", "cozuldu",
    "zirve", "rekoru", "ivme", "fazla", "patladi", "siradisi", "yuksek",
    "yukselttI", "yukseltti",
    # EN
    "surge", "surged", "rally", "rallied", "gain", "gains", "gained",
    "profit", "profits", "beat", "beats", "record", "high", "upgrade",
    "upgraded", "bullish", "strong", "growth", "acquire", "acquisition",
    "partnership", "deal", "outperform", "rises", "rise", "rose", "jump",
    "jumped", "soar", "soared", "climb", "climbed", "boost", "boosted",
    "expand", "expands", "expansion", "beats", "exceeds", "raises",
    "raised", "optimistic", "positive", "success", "successful", "win",
    "wins", "breakthrough", "milestone", "approve", "approved", "launch",
    "launched",
}

_NEG_WORDS = {
    # TR
    "dustu", "dusus", "kaybetti", "kayip", "zarar", "iflas", "kriz",
    "daralma", "issizlik", "protest", "tehdit", "olumsuz", "negatif",
    "geriledi", "gerileme", "darbe", "cokus", "coktU", "coktu", "cezalandirildi",
    "ceza", "sorusturma", "sorun", "kesinti", "grev", "dava", "borclu",
    "borc", "batik", "hisseler dustu", "satis baskisi", "panik", "sert dusus",
    "yasak", "durdurdu", "askiya", "iptal", "risk", "endise", "daraldi",
    "bosaltti", "bosaldi", "kayiplar", "dipte", "dip",
    # EN
    "drop", "drops", "dropped", "plunge", "plunged", "loss", "losses",
    "miss", "missed", "downgrade", "downgraded", "bearish", "crash",
    "crashed", "recession", "layoff", "layoffs", "lawsuit", "probe",
    "investigation", "decline", "declines", "declined", "fall", "falls",
    "fell", "fallen", "slump", "slumped", "tumble", "tumbled", "warn",
    "warning", "cut", "cuts", "slash", "slashed", "weak", "weakness",
    "concern", "concerns", "worries", "fears", "sink", "sank", "sunk",
    "halt", "halted", "ban", "banned", "fine", "fined", "bankrupt",
    "bankruptcy", "default", "downturn", "negative", "risk", "risks",
    "threat", "shutdown", "strike",
}

_WORD_RE = re.compile(r"[A-Za-zÇĞİıÖŞÜçğıöşü]+", re.UNICODE)


def _tokenize(text: str) -> list:
    if not text:
        return []
    return [w.lower() for w in _WORD_RE.findall(text)]


def classify(title: str, summary: str = "") -> Tuple[str, int]:
    """Baslik + ozet'e bakarak (label, score) dondurur.

    label: 'positive' | 'neutral' | 'negative'
    score: pos - neg. Negatif kelimeler biraz daha agirliklidir cunku
    piyasa haberlerinde 'dusus' tipik olarak daha belirleyicidir.
    """
    text = f"{title or ''} {summary or ''}"
    tokens = _tokenize(text)
    if not tokens:
        return ("neutral", 0)

    pos = sum(1 for t in tokens if t in _POS_WORDS)
    neg = sum(1 for t in tokens if t in _NEG_WORDS)

    score = pos - int(neg * 1.15)

    if score >= 1:
        return ("positive", score)
    if score <= -1:
        return ("negative", score)
    return ("neutral", score)
