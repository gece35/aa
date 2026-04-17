# Nebula Scanner

BIST ve US hisselerini 5 teknik gostergeye gore (RSI, MACD, Bollinger, EMA50, Stochastic) tarayan ve 0-5 arasi puanlayan yuksek performansli Flask + vanilla JS uygulamasi.

## Mimari

- **Toplu veri indirme**: `yfinance.download(..., threads=True)` tek seferde tum hisseleri cokuslar.
- **In-memory TTL cache (10 dk)**: `/api/scan` ve `/api/news` sonuclari bellekte tutulur; `force=1` parametresi cache'i bypass eder.
- **Threaded skor hesabi**: `ThreadPoolExecutor` ile paralel indikator hesabi.
- **Puanlama motoru**: Her AL sinyali icin +1 puan. RSI / MACD / BBands / EMA50 / Stoch.

## Klasor Yapisi

```
app.py                 # Flask giris noktasi
backend/
  __init__.py
  cache.py             # TTLCache
  data_fetcher.py      # yfinance batch fetch
  scoring.py           # 5 indikator + skor
  scanner.py           # tarama orkestrasyonu
  news.py              # RSS feed toplayici
  tickers.py           # BIST + US sembol listeleri
frontend/
  index.html           # Glassmorphism arayuz
  style.css            # Koyu mod + galaksi + neon
  app.js               # Vanilla JS etkilesim
requirements.txt
```

## Kurulum

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

`http://localhost:5000` adresini tarayiciyla ac.

## API

| Endpoint | Aciklama |
|----------|----------|
| `GET /api/markets` | Desteklenen pazarlar |
| `GET /api/scan?market=us&force=0` | Tarama sonucu (skora gore sirali) |
| `GET /api/news?market=bist` | Piyasa haberleri |
| `GET /api/stock/<symbol>` | Tek hisse detayi (skor + 60g gecmis) |
| `GET /api/health` | Saglik |
| `POST /api/cache/clear` | Tum cache temizle |

## Notlar

- Yatirim tavsiyesi degildir, egitim amaclidir.
- Ilk istek uzun surebilir (yfinance tum hisseleri indirir). Sonraki 10 dakika cache'ten yanit doner.
