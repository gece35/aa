"""Desteklenen pazarlardaki hisse sembollerinin listesi.

BIST sembolleri yfinance formatinda ``.IS`` uzantisiyla tutulur.
US sembolleri ham sekilde (AAPL, MSFT, ...) tutulur.
"""

BIST_TICKERS = [
    # Bankalar
    "AKBNK.IS", "GARAN.IS", "ISCTR.IS", "YKBNK.IS", "HALKB.IS", "VAKBN.IS",
    "ALBRK.IS", "SKBNK.IS", "QNBTR.IS", "TSKB.IS", "ICBCT.IS",
    # Havacilik / Ulasim / Lojistik
    "THYAO.IS", "PGSUS.IS", "TAVHL.IS", "CLEBI.IS", "TLMAN.IS", "GSDDE.IS",
    "BEYAZ.IS", "RYSAS.IS",
    # Savunma / Teknoloji / Bilisim
    "ASELS.IS", "OTKAR.IS", "LOGO.IS", "KAREL.IS", "INDES.IS", "ARENA.IS",
    "ESCOM.IS", "DESPC.IS", "DGATE.IS", "PAPIL.IS", "SMART.IS", "NETAS.IS",
    "FONET.IS",
    # Holding
    "SAHOL.IS", "ENKAI.IS", "KCHOL.IS", "DOHOL.IS", "ALARK.IS", "AGHOL.IS",
    "TKFEN.IS", "GSDHO.IS", "NTHOL.IS", "ECILC.IS", "IHLAS.IS",
    "IEYHO.IS", "KUTPO.IS",
    # Enerji / Rafineri / Elektrik
    "TUPRS.IS", "PETKM.IS", "AYGAZ.IS", "ENJSA.IS", "AKSEN.IS", "ZOREN.IS",
    "ODAS.IS", "AKENR.IS", "AKSA.IS", "AKFGY.IS", "BIOEN.IS", "CWENE.IS",
    "GWIND.IS", "NATEN.IS", "MARBL.IS", "AKFYE.IS", "ENERY.IS",
    # Metal / Cimento / Cam / Demir-Celik
    "EREGL.IS", "KRDMD.IS", "KRDMA.IS", "KRDMB.IS", "SISE.IS", "CIMSA.IS",
    "AKCNS.IS", "OYAKC.IS", "CEMTS.IS", "CEMAS.IS", "BURCE.IS", "BURVA.IS",
    "DMSAS.IS", "ISDMR.IS", "KUYAS.IS", "KATMR.IS", "NUHCM.IS",
    "BTCIM.IS", "GOLTS.IS", "KONYA.IS",
    # Otomotiv / Beyaz Esya / Dayanikli Tuketim
    "ARCLK.IS", "VESTL.IS", "TOASO.IS", "FROTO.IS", "TTRAK.IS", "DOAS.IS",
    "KARSN.IS", "TMSN.IS", "EGEEN.IS", "PARSN.IS", "EGSER.IS",
    "BRISA.IS", "KORDS.IS", "GOODY.IS",
    # Perakende / Gida / Icecek
    "BIMAS.IS", "MGROS.IS", "SOKM.IS", "CCOLA.IS", "AEFES.IS", "ULKER.IS",
    "TATGD.IS", "PINSU.IS", "KNFRT.IS", "PNSUT.IS", "BANVT.IS",
    "CVKMD.IS", "MAVI.IS", "DERIM.IS", "TKNSA.IS", "BIZIM.IS",
    "VAKKO.IS", "ZRGYO.IS",
    # Telekom / Medya
    "TCELL.IS", "TTKOM.IS", "HURGZ.IS", "DGGYO.IS",
    # GYO / Insaat
    "EKGYO.IS", "ISGYO.IS", "TRGYO.IS", "OZKGY.IS", "AGYO.IS", "AKSGY.IS",
    "ATAGY.IS", "KLGYO.IS", "MRGYO.IS", "NUGYO.IS", "SRVGY.IS", "VKGYO.IS",
    "ORGE.IS",
    # Kimya / Ilac / Saglik
    "SASA.IS", "HEKTS.IS", "BAGFS.IS", "DEVA.IS", "MPARK.IS", "LKMNH.IS",
    "GENIL.IS", "SODSN.IS", "RTALB.IS", "ALKIM.IS", "BRKSN.IS", "POLTK.IS",
    "EGEPO.IS",
    # Tekstil / Giyim
    "YATAS.IS", "MNDRS.IS", "KRTEK.IS", "BLCYT.IS", "HATEK.IS", "DAGI.IS",
    # Madencilik / Endustri / Diger
    "SMRTG.IS", "IZMDC.IS", "BRSAN.IS",
    "SARKY.IS", "TUKAS.IS", "AYES.IS", "PENTA.IS", "SAFKR.IS",
    # Lojistik / Gida Tedarik
    "REEDR.IS", "PETUN.IS", "EBEBK.IS", "JANTS.IS",
]

# tekrar edenleri temizle, sirayi koru
_seen = set()
BIST_TICKERS = [t for t in BIST_TICKERS if not (t in _seen or _seen.add(t))]

US_TICKERS = [
    # Mega-cap Teknoloji
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "ORCL", "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "INTU",
    "NOW", "IBM", "PANW", "SNPS", "CDNS", "KLAC", "LRCX", "AMAT", "MU",
    "MRVL", "ADI", "NXPI", "MCHP", "FTNT", "CRWD", "ZS", "DDOG", "SNOW",
    "PLTR", "ANET", "WDAY", "ADSK", "TEAM", "MDB", "NET", "OKTA",
    # Iletisim / Medya / Eglence
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "EA", "TTWO", "RBLX",
    "SPOT", "WBD", "LYV", "SNAP", "PINS", "RDDT",
    # Finans / Sigorta
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "USB",
    "PNC", "TFC", "COF", "BK", "STT", "ICE", "CME", "SPGI", "MCO",
    "AON", "AJG", "BRK-B", "PGR", "ALL", "TRV", "MET", "PRU", "AIG",
    # Odeme / Fintech
    "V", "MA", "PYPL", "XYZ", "COIN", "FIS",
    # Perakende / Tuketim
    "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "KO", "PEP",
    "TJX", "ROST", "ULTA", "DG", "DLTR", "KR", "YUM", "CMG", "ORLY",
    "AZO", "EBAY", "ETSY", "LULU", "DECK", "BBY",
    # Tuketim Mallari
    "PG", "CL", "KMB", "CHD", "CLX", "EL", "MDLZ", "MO", "PM", "KHC",
    "GIS", "HSY", "STZ", "MNST", "KDP",
    # Saglik / Ilac / Biotek
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "CVS", "TMO", "ABT", "DHR",
    "BMY", "AMGN", "GILD", "REGN", "VRTX", "BIIB", "ZTS", "ISRG", "SYK",
    "MDT", "BSX", "ELV", "HUM", "CI", "HCA", "ILMN",
    # Enerji / Petrol
    "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "VLO", "MPC", "OXY", "KMI",
    "WMB", "OKE", "DVN", "HAL", "BKR", "FANG",
    # Endustri / Havacilik / Savunma
    "BA", "CAT", "GE", "HON", "LMT", "RTX", "DE", "NOC", "GD", "EMR",
    "ETN", "MMM", "ITW", "PH", "JCI", "CMI", "CSX", "NSC", "UNP", "UPS",
    "FDX", "LHX", "DAL", "UAL", "AAL", "LUV", "GEV",
    # Otomotiv / Ulastirma
    "F", "GM", "RIVN", "LCID", "UBER", "LYFT", "ABNB", "DASH",
    # Emlak / REITs
    "PLD", "AMT", "EQIX", "CCI", "SPG", "PSA", "O", "WELL", "DLR", "EXR",
    # Temel Malzeme / Kimya
    "LIN", "SHW", "APD", "ECL", "DD", "DOW", "NEM", "FCX", "NUE",
    # Utility
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL",
    # Diger gozde
    "SMCI", "ASML", "TSM", "BABA", "JD", "PDD", "NIO", "XPEV", "SHOP",
    "ARM", "MSTR",
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
