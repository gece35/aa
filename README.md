# Nebula Scanner

BIST (162 hisse) ve ABD borsası hisselerini 4 teknik gösterge + hacim filtresiyle tarayan ve **0-10** arası puanlayan Flask + Vanilla JS uygulaması. Railway üzerinde canlıya alınmıştır.

## Puanlama Motoru (0-10)

| Gösterge | Max Puan | Sinyal Kriteri |
|----------|----------|----------------|
| **TREND** (EMA20/50/200) | 3 | Fiyat > EMA20 > EMA50 > EMA200 dizilimi |
| **MOMENTUM** (MACD) | 3 | MACD sıfır çizgisi altından yukarı kesişi |
| **RSI (14)** | 2 | RSI 30'u yukarı keser (aşırı satımdan çıkış); >70 ise -1 ceza |
| **VOLATİLİTE** (Bollinger 20,2) | 2 | Alt banda dokunup yeşil kapanış |
| **Hacim Onayı** (filtre) | -1 | MACD/BB tam puan + hacim ortalamanın altındaysa -1 |

## Mimari

- **Factory pattern Flask app** — `create_app()` ile oluşturulan tek uygulama
- **Toplu veri indirme** — `yfinance.download(..., threads=True)` ile tüm hisseler tek seferde
- **In-memory TTL cache** — `/api/scan`, `/api/stock`, `/api/news` yanıtları önbelleklenir; `force=1` bypass eder
- **Formasyon tespiti** — Son 90 barda 12+ teknik formasyon (İkili Tepe/Dip, OBO, Kama, Üçgen, Bayrak vb.)
- **Lexicon tabanlı sentiment** — Haber başlıklarını TR+EN kelime listesiyle pozitif/nötr/negatif sınıflandırır
- **Planlı arka plan işleri** — `worker.py` ile periyodik fiyat alarmı kontrolü

## Klasör Yapısı

```
app.py                   # Flask giriş noktası (create_app factory)
backend/
  auth.py                # Kayıt, giriş, e-posta doğrulama, şifre sıfırlama
  billing.py             # Ödeme ve abonelik yönetimi
  newsletter.py          # Bülten aboneliği
  support.py             # Destek talepleri
  cache.py               # TTL cache (scan/stock/news)
  config.py              # Ortam değişkenleri ve sabitler
  data_fetcher.py        # yfinance batch OHLCV indirme
  db.py                  # SQLAlchemy + Flask-Migrate
  email.py               # İşlemsel e-posta gönderimi
  limits.py              # Plan tanımları ve gating decorator'lar
  models.py              # User, Watchlist, Portfolio, StockComment
  news.py                # RSS haber toplayıcı
  patterns.py            # 12+ teknik formasyon tespiti
  quota_store.py         # Günlük kullanım sayacı (in-memory / Redis)
  scanner.py             # Tarama orkestrasyonu
  scoring.py             # 10 puanlık gösterge motoru
  sectors.py             # Sektör etiketleri
  security.py            # Rate limiting ve güvenlik başlıkları
  sentiment.py           # Lexicon tabanlı haber duygu analizi
  tickers.py             # BIST (162) + US sembol listeleri
  worker.py              # Arka plan alarm kontrolü
frontend/
  index.html             # Ana tarayıcı arayüzü (glassmorphism / dark)
  rehber.html            # Kullanım kılavuzu
  about.html             # Hakkında
  faq.html               # Sıkça sorulan sorular
  blog/                  # Blog yazıları
  legal/                 # Gizlilik, kullanım koşulları
  app.js                 # Vanilla JS etkileşim
  style.css              # Koyu mod + galaksi + neon
requirements.txt
nixpacks.toml            # Railway derleme konfigürasyonu
```

## Kurulum

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # değerleri doldur
flask db upgrade
python app.py
```

`http://localhost:5000` adresini tarayıcıyla aç.

## Planlar

| Özellik | Misafir | Üye (Ücretsiz) | Premium |
|---------|---------|----------------|---------|
| BIST tarama | 30 hisse | Tümü (162) | Tümü |
| US tarama | — | Tümü | Tümü |
| Hisse detayı/gün | 5 | Sınırsız | Sınırsız |
| İzleme listesi | — | 100 | 100 |
| Portföy | — | 50 pozisyon | 50 pozisyon |
| Fiyat alarmları | — | 50 | 50 |
| Formasyon tespiti | — | Tümü | Tümü |
| CSV dışa aktarım | — | Evet | Evet |

## API

| Endpoint | Yöntem | Açıklama |
|----------|--------|----------|
| `GET /api/markets` | — | Desteklenen pazarlar |
| `GET /api/scan?market=bist&force=0` | — | Tarama (skora göre sıralı) |
| `GET /api/stock/<symbol>` | — | Hisse detayı, skor, 60g geçmiş, formasyonlar |
| `GET /api/news?market=bist` | — | Piyasa haberleri + sentiment |
| `GET /api/news/stock/<symbol>` | — | Hisseye özel haberler |
| `GET /api/exchange-rate` | — | USD/TRY kuru |
| `GET /api/backtest` | — | Sinyal bazlı backtest |
| `GET /api/alerts` | Auth | Alarmları listele |
| `POST /api/alerts` | Auth | Alarm oluştur |
| `DELETE /api/alerts/<id>` | Auth | Alarm sil |
| `GET /api/alerts/triggered` | Auth | Tetiklenen alarmlar |
| `GET /api/watchlist` | Auth | İzleme listesi |
| `POST /api/watchlist` | Auth | Listeye ekle |
| `GET /api/portfolio` | Auth | Portföy pozisyonları |
| `POST /api/portfolio` | Auth | Pozisyon ekle |
| `GET /api/comments/<symbol>` | — | Topluluk yorumları |
| `POST /api/comments/<symbol>` | Auth | Yorum ekle |
| `GET /api/health` | — | Sağlık kontrolü |
| `POST /api/cache/clear` | Admin | Tüm cache temizle |

## Auth API (`/auth`)

`/auth/signup` · `/auth/login` · `/auth/logout` · `/auth/me` · `/auth/forgot` · `/auth/reset` · `/auth/verify` · `/auth/resend-verify` · `/auth/export` · `/auth/consent`

## Notlar

- Yatırım tavsiyesi değildir, eğitim amaçlıdır.
- İlk istek uzun sürebilir (yfinance tüm hisseleri indirir). Sonraki yanıtlar önbellekten döner.
