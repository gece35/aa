"""Sembol → sektör eşlemesi (portföy seviyesinde sektör konsantrasyonu sınırı için).

Bilinmeyen semboller "other" kategorisine düşer.
"""

from __future__ import annotations

# ── BIST sektörleri ──────────────────────────────────────────────────────────
_BIST_SECTORS = {
    # Bankalar
    "AKBNK.IS": "bank", "GARAN.IS": "bank", "ISCTR.IS": "bank",
    "YKBNK.IS": "bank", "HALKB.IS": "bank", "VAKBN.IS": "bank",
    "ALBRK.IS": "bank", "SKBNK.IS": "bank", "QNBTR.IS": "bank",
    "TSKB.IS":  "bank", "ICBCT.IS": "bank",
    # Havacılık / Ulaşım / Lojistik
    "THYAO.IS": "aviation", "PGSUS.IS": "aviation", "TAVHL.IS": "aviation",
    "CLEBI.IS": "aviation", "TLMAN.IS": "aviation", "GSDDE.IS": "aviation",
    "BEYAZ.IS": "aviation", "RYSAS.IS": "aviation",
    # Savunma / Teknoloji / Bilişim
    "ASELS.IS": "tech", "OTKAR.IS": "tech", "LOGO.IS":  "tech",
    "KAREL.IS": "tech", "INDES.IS": "tech", "ARENA.IS": "tech",
    "ESCOM.IS": "tech", "DESPC.IS": "tech", "DGATE.IS": "tech",
    "PAPIL.IS": "tech", "SMART.IS": "tech", "NETAS.IS": "tech",
    "FONET.IS": "tech",
    # Holding
    "SAHOL.IS": "holding", "ENKAI.IS": "holding", "KCHOL.IS": "holding",
    "DOHOL.IS": "holding", "ALARK.IS": "holding", "AGHOL.IS": "holding",
    "TKFEN.IS": "holding", "GSDHO.IS": "holding", "NTHOL.IS": "holding",
    "ECILC.IS": "holding", "IHLAS.IS": "holding", "IEYHO.IS": "holding",
    "KUTPO.IS": "holding",
    # Enerji / Rafineri / Elektrik
    "TUPRS.IS": "energy", "PETKM.IS": "energy", "AYGAZ.IS": "energy",
    "ENJSA.IS": "energy", "AKSEN.IS": "energy", "ZOREN.IS": "energy",
    "ODAS.IS":  "energy", "AKENR.IS": "energy", "AKSA.IS":  "energy",
    "AKFGY.IS": "energy", "BIOEN.IS": "energy", "CWENE.IS": "energy",
    "GWIND.IS": "energy", "NATEN.IS": "energy", "MARBL.IS": "energy",
    "AKFYE.IS": "energy", "ENERY.IS": "energy",
    # Metal / Çimento / Cam / Demir-Çelik
    "EREGL.IS": "metal_cement", "KRDMD.IS": "metal_cement", "KRDMA.IS": "metal_cement",
    "KRDMB.IS": "metal_cement", "SISE.IS":  "metal_cement", "CIMSA.IS": "metal_cement",
    "AKCNS.IS": "metal_cement", "OYAKC.IS": "metal_cement", "CEMTS.IS": "metal_cement",
    "CEMAS.IS": "metal_cement", "BURCE.IS": "metal_cement", "BURVA.IS": "metal_cement",
    "DMSAS.IS": "metal_cement", "ISDMR.IS": "metal_cement", "KUYAS.IS": "metal_cement",
    "KATMR.IS": "metal_cement", "NUHCM.IS": "metal_cement", "BTCIM.IS": "metal_cement",
    "GOLTS.IS": "metal_cement", "KONYA.IS": "metal_cement",
    # Otomotiv / Beyaz Eşya / Dayanıklı Tüketim
    "ARCLK.IS": "auto_consumer", "VESTL.IS": "auto_consumer", "TOASO.IS": "auto_consumer",
    "FROTO.IS": "auto_consumer", "TTRAK.IS": "auto_consumer", "DOAS.IS":  "auto_consumer",
    "KARSN.IS": "auto_consumer", "TMSN.IS":  "auto_consumer", "EGEEN.IS": "auto_consumer",
    "PARSN.IS": "auto_consumer", "EGSER.IS": "auto_consumer", "BRISA.IS": "auto_consumer",
    "KORDS.IS": "auto_consumer", "GOODY.IS": "auto_consumer",
    # Perakende / Gıda / İçecek
    "BIMAS.IS": "retail_food", "MGROS.IS": "retail_food", "SOKM.IS":  "retail_food",
    "CCOLA.IS": "retail_food", "AEFES.IS": "retail_food", "ULKER.IS": "retail_food",
    "TATGD.IS": "retail_food", "PINSU.IS": "retail_food", "KNFRT.IS": "retail_food",
    "PNSUT.IS": "retail_food", "BANVT.IS": "retail_food", "CVKMD.IS": "retail_food",
    "MAVI.IS":  "retail_food", "DERIM.IS": "retail_food", "TKNSA.IS": "retail_food",
    "BIZIM.IS": "retail_food", "VAKKO.IS": "retail_food", "ZRGYO.IS": "retail_food",
    # Telekom / Medya
    "TCELL.IS": "telecom_media", "TTKOM.IS": "telecom_media",
    "HURGZ.IS": "telecom_media", "DGGYO.IS": "telecom_media",
    # GYO / İnşaat
    "EKGYO.IS": "real_estate", "ISGYO.IS": "real_estate", "TRGYO.IS": "real_estate",
    "OZKGY.IS": "real_estate", "AGYO.IS":  "real_estate", "AKSGY.IS": "real_estate",
    "ATAGY.IS": "real_estate", "KLGYO.IS": "real_estate", "MRGYO.IS": "real_estate",
    "NUGYO.IS": "real_estate", "SRVGY.IS": "real_estate", "VKGYO.IS": "real_estate",
    "ORGE.IS":  "real_estate",
    # Kimya / İlaç / Sağlık
    "SASA.IS":  "chemical_health", "HEKTS.IS": "chemical_health",
    "BAGFS.IS": "chemical_health", "DEVA.IS":  "chemical_health",
    "MPARK.IS": "chemical_health", "LKMNH.IS": "chemical_health",
    "GENIL.IS": "chemical_health", "SODSN.IS": "chemical_health",
    "RTALB.IS": "chemical_health", "ALKIM.IS": "chemical_health",
    "BRKSN.IS": "chemical_health", "POLTK.IS": "chemical_health",
    "EGEPO.IS": "chemical_health",
    # Tekstil
    "YATAS.IS": "textile", "MNDRS.IS": "textile", "KRTEK.IS": "textile",
    "BLCYT.IS": "textile", "HATEK.IS": "textile", "DAGI.IS":  "textile",
    # Madencilik / Endüstriyel
    "SMRTG.IS": "industrial", "IZMDC.IS": "industrial", "BRSAN.IS": "industrial",
    "SARKY.IS": "industrial", "TUKAS.IS": "industrial", "AYES.IS":  "industrial",
    "PENTA.IS": "industrial", "SAFKR.IS": "industrial", "REEDR.IS": "industrial",
    "PETUN.IS": "industrial", "EBEBK.IS": "industrial", "JANTS.IS": "industrial",
}

# ── US sektörleri ────────────────────────────────────────────────────────────
_US_SECTORS = {
    # Mega-cap Teknoloji
    "AAPL": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
    "AMZN": "tech", "META": "tech", "NVDA": "tech", "TSLA": "tech",
    "AVGO": "tech", "ORCL": "tech", "ADBE": "tech", "CRM":  "tech",
    "AMD":  "tech", "INTC": "tech", "CSCO": "tech", "QCOM": "tech",
    "TXN":  "tech", "INTU": "tech", "NOW":  "tech", "IBM":  "tech",
    "PANW": "tech", "SNPS": "tech", "CDNS": "tech", "KLAC": "tech",
    "LRCX": "tech", "AMAT": "tech", "MU":   "tech", "MRVL": "tech",
    "ADI":  "tech", "NXPI": "tech", "MCHP": "tech", "FTNT": "tech",
    "CRWD": "tech", "ZS":   "tech", "DDOG": "tech", "SNOW": "tech",
    "PLTR": "tech", "ANET": "tech", "WDAY": "tech", "ADSK": "tech",
    "TEAM": "tech", "MDB":  "tech", "NET":  "tech", "OKTA": "tech",
    # İletişim / Medya / Eğlence
    "NFLX": "media_comm", "DIS":  "media_comm", "CMCSA": "media_comm",
    "T":    "media_comm", "VZ":   "media_comm", "TMUS": "media_comm",
    "EA":   "media_comm", "TTWO": "media_comm", "RBLX": "media_comm",
    "SPOT": "media_comm", "WBD":  "media_comm", "LYV":  "media_comm",
    "SNAP": "media_comm", "PINS": "media_comm", "RDDT": "media_comm",
    # Finans / Sigorta / Ödeme
    "JPM":  "finance", "BAC":  "finance", "WFC":  "finance", "GS":   "finance",
    "MS":   "finance", "C":    "finance", "AXP":  "finance", "BLK":  "finance",
    "SCHW": "finance", "USB":  "finance", "PNC":  "finance", "TFC":  "finance",
    "COF":  "finance", "BK":   "finance", "STT":  "finance", "ICE":  "finance",
    "CME":  "finance", "SPGI": "finance", "MCO":  "finance", "AON":  "finance",
    "AJG":  "finance", "BRK-B":"finance", "PGR":  "finance", "ALL":  "finance",
    "TRV":  "finance", "MET":  "finance", "PRU":  "finance", "AIG":  "finance",
    "V":    "finance", "MA":   "finance", "PYPL": "finance", "XYZ":  "finance",
    "COIN": "finance", "FIS":  "finance",
    # Perakende / Tüketim
    "WMT":  "retail", "COST": "retail", "TGT":  "retail", "HD":   "retail",
    "LOW":  "retail", "NKE":  "retail", "SBUX": "retail", "MCD":  "retail",
    "KO":   "retail", "PEP":  "retail", "TJX":  "retail", "ROST": "retail",
    "ULTA": "retail", "DG":   "retail", "DLTR": "retail", "KR":   "retail",
    "YUM":  "retail", "CMG":  "retail", "ORLY": "retail", "AZO":  "retail",
    "EBAY": "retail", "ETSY": "retail", "LULU": "retail", "DECK": "retail",
    "BBY":  "retail",
    # Tüketim Malları
    "PG":   "consumer_goods", "CL":   "consumer_goods", "KMB":  "consumer_goods",
    "CHD":  "consumer_goods", "CLX":  "consumer_goods", "EL":   "consumer_goods",
    "MDLZ": "consumer_goods", "MO":   "consumer_goods", "PM":   "consumer_goods",
    "KHC":  "consumer_goods", "GIS":  "consumer_goods", "HSY":  "consumer_goods",
    "STZ":  "consumer_goods", "MNST": "consumer_goods", "KDP":  "consumer_goods",
    # Sağlık / İlaç / Biyotek
    "JNJ":  "health", "PFE":  "health", "MRK":  "health", "ABBV": "health",
    "LLY":  "health", "UNH":  "health", "CVS":  "health", "TMO":  "health",
    "ABT":  "health", "DHR":  "health", "BMY":  "health", "AMGN": "health",
    "GILD": "health", "REGN": "health", "VRTX": "health", "BIIB": "health",
    "ZTS":  "health", "ISRG": "health", "SYK":  "health", "MDT":  "health",
    "BSX":  "health", "ELV":  "health", "HUM":  "health", "CI":   "health",
    "HCA":  "health", "ILMN": "health",
    # Enerji / Petrol
    "XOM":  "energy", "CVX":  "energy", "COP":  "energy", "EOG":  "energy",
    "SLB":  "energy", "PSX":  "energy", "VLO":  "energy", "MPC":  "energy",
    "OXY":  "energy", "KMI":  "energy", "WMB":  "energy", "OKE":  "energy",
    "DVN":  "energy", "HAL":  "energy", "BKR":  "energy", "FANG": "energy",
    # Endüstri / Havacılık / Savunma / Lojistik
    "BA":   "industrial", "CAT":  "industrial", "GE":   "industrial",
    "HON":  "industrial", "LMT":  "industrial", "RTX":  "industrial",
    "DE":   "industrial", "NOC":  "industrial", "GD":   "industrial",
    "EMR":  "industrial", "ETN":  "industrial", "MMM":  "industrial",
    "ITW":  "industrial", "PH":   "industrial", "JCI":  "industrial",
    "CMI":  "industrial", "CSX":  "industrial", "NSC":  "industrial",
    "UNP":  "industrial", "UPS":  "industrial", "FDX":  "industrial",
    "LHX":  "industrial", "DAL":  "industrial", "UAL":  "industrial",
    "AAL":  "industrial", "LUV":  "industrial", "GEV":  "industrial",
    # Otomotiv / Ulaştırma
    "F":    "auto_transport", "GM":   "auto_transport", "RIVN": "auto_transport",
    "LCID": "auto_transport", "UBER": "auto_transport", "LYFT": "auto_transport",
    "ABNB": "auto_transport", "DASH": "auto_transport",
    # Emlak / REITs
    "PLD":  "real_estate", "AMT":  "real_estate", "EQIX": "real_estate",
    "CCI":  "real_estate", "SPG":  "real_estate", "PSA":  "real_estate",
    "O":    "real_estate", "WELL": "real_estate", "DLR":  "real_estate",
    "EXR":  "real_estate",
    # Temel Malzeme / Kimya
    "LIN":  "materials", "SHW":  "materials", "APD":  "materials",
    "ECL":  "materials", "DD":   "materials", "DOW":  "materials",
    "NEM":  "materials", "FCX":  "materials", "NUE":  "materials",
    # Utility
    "NEE":  "utility", "DUK":  "utility", "SO":   "utility", "D":    "utility",
    "AEP":  "utility", "SRE":  "utility", "EXC":  "utility", "XEL":  "utility",
    # Diğer / ADR
    "SMCI": "tech", "ASML": "tech", "TSM":  "tech", "ARM":  "tech",
    "BABA": "tech", "JD":   "retail", "PDD":  "retail", "NIO":  "auto_transport",
    "XPEV": "auto_transport", "SHOP": "tech", "MSTR": "finance",
}


def get_sector(symbol: str) -> str:
    """Sembolün sektörünü döndürür. Bilinmeyenler 'other'."""
    if not symbol:
        return "other"
    if symbol in _BIST_SECTORS:
        return _BIST_SECTORS[symbol]
    if symbol in _US_SECTORS:
        return _US_SECTORS[symbol]
    return "other"
