# Nebula Scanner

BIST (162 hisse) ve ABD borsası hisselerini **kesişim bazlı sinyal motoru** ile tarayan ve **0-10** arası puanlayan Flask + Vanilla JS uygulaması. Puanlama **kesişim tazeliğine** dayanır; bir sinyal ne kadar yeni kesilmişse o kadar yüksek puan alır, lineer sönme ile zamanla sıfıra iner. Railway üzerinde canlıya alınmıştır.

## Puanlama Motoru (0-10) — kesişim bazlı, lineer sönme

Tek vektörize motor (`backend/scoring.py` → `compute_score_frame`) hem canlı tarama hem backtest tarafından kullanılır (tek kaynak, sapma yok).

| Sinyal | Max Puan | Ne Ölçer? |
|--------|----------|-----------|
| **MACD × Sinyal hattı** | 2.0 | MACD çizgisinin sinyal hattını yukarı kesmesi |
| **MACD × Sıfır hattı** | 1.0 | MACD çizgisinin 0 hattını yukarı kesmesi |
| **RSI × RSI-EMA9** | 1.5 | RSI'ın kendi sinyal hattını yukarı kesmesi |
| **Fiyat × EMA30** | 0.5 | Fiyatın EMA30'u yukarı kesmesi |
| **Fiyat × EMA50** | 0.75 | Fiyatın EMA50'yi yukarı kesmesi |
| **Fiyat × EMA200** | 0.75 | Fiyatın EMA200'ü yukarı kesmesi |
| **DI+ × DI−** | 1.5 | +DI'ın −DI'yı yukarı kesmesi (ADX) |
| **Hacim Onayı** | 1.0 | Kesişimle eş zamanlı hacim spike'ı (bonus) |
| **Genişleme Cezası** | −2.0 | 52 haftalık zirveye yakınlık + EMA20 sapma cezası |

Sinyaller kesişim anında tam puanı alır, `CROSS_LOOKBACK=20` bar içinde lineer sönme ile sıfıra iner. Ham toplam `EWM(span=2)` ile yumuşatılır ve 0-10'a clip edilir.

## Formasyon Tespiti (`backend/patterns.py`) — v2

Son 120 barda 8 teknik formasyon tespiti; her formasyon için güven skoru, geçerlilik kontrolü ve işaretçi/trend çizgisi koordinatları üretilir.

| Formasyon | Yön | Açıklama |
|-----------|-----|----------|
| İkili Tepe | Düşüş | İki benzer tepe; hacim onayı ve tazelik kontrolü |
| İkili Dip | Yükseliş | İki benzer dip; hacim onayı ve tazelik kontrolü |
| Omuz-Baş-Omuz | Düşüş | Gerçek Low bazlı neckline; boyun kırılım tespiti |
| Ters Omuz-Baş-Omuz | Yükseliş | Boyun kırılımında güven seviyesi yüksek |
| Simetrik/Düşen/Yükselen Üçgen | Nötr/Mix | 20-30-45-60 bar pencerelerinde en iyi R² uyumu |
| Yükselen/Düşen Kama | Düşüş/Yükseliş | Regresyon eğimi + yakınsama filtresi |
| Boğa/Ayı Bayrağı | Yükseliş/Düşüş | Sap kuvveti + konsolidasyon dar aralık kontrolü |

**Geçerlilik filtresi:** Fiyat neckline/formasyon sınırından >%7 uzaklaşmışsa formasyon otomatik olarak listeden çıkarılır.

## Otomatik Trend Çizgileri (`backend/patterns.py` → `detect_auto_trendlines`)

- **Kısa vadeli** (son 60 bar, window=3, min_gap=8): Günlük destek/direnç trend çizgileri
- **Uzun vadeli** (son 200 bar, window=7, min_gap=20): Haftalık perspektif trend çizgileri

Her vade için ayrı destek ve direnç çizgisi üretilir; grafik üzerinde canlandırılır.

## Mimari

- **Factory pattern Flask app** — `create_app()` ile oluşturulan tek uygulama
- **Toplu veri indirme** — `yfinance.download(..., threads=True)` ile tüm hisseler tek seferde
- **In-memory TTL cache** — `/api/scan`, `/api/stock`, `/api/news` yanıtları önbelleklenir; `force=1` bypass eder
- **Lexicon tabanlı sentiment** — Haber başlıklarını TR+EN kelime listesiyle pozitif/nötr/negatif sınıflandırır
- **Planlı arka plan işleri** — `worker.py` ile periyodik fiyat alarmı kontrolü
- **Destek/Direnç seviyeleri** — Pivot tabanlı kümeleme ile `supports` / `resistances` + otomatik SL/TP hesabı

## Aralıklı Tekrar Sistemi

Projeden bağımsız, ders takibi için aralıklı tekrar (spaced repetition) aracı.

### CLI (`tekrar.py`)

```bash
python tekrar.py ekle "Matematik" "Türev"   # Ders ekle (1g/1h/1ay/3ay tekrar planı oluşturur)
python tekrar.py tablo                       # Tüm dersleri ve tekrar tarihlerini göster
python tekrar.py bugun                       # Bugünkü ve 7 gün içindeki tekrarları listele
python tekrar.py sil 3                       # Kayıt sil
python tekrar.py ics                         # .ics takvim dosyasını yeniden üret
```

Tekrar tarihleri: `+1 gün → +1 hafta → +1 ay → +3 ay`. `.ics` dosyası telefon takvimine aktarılabilir, 09:00'da otomatik alarm düşer.

### API (`backend/repetition.py` + `backend/calendar_api.py`)

- `build_repetition_schedule(topic, subject, start_date)` → takvim etkinliği listesi üretir
- Google Calendar API entegrasyonu (service account); `GOOGLE_CALENDAR_CREDENTIALS` env var ile devreye girer
- Hafta içi 17:00, hafta sonu 14:00 hatırlatma saatleri; her tekrar için farklı renk kodu

## Klasör Yapısı

```
app.py                   # Flask giriş noktası (create_app factory)
tekrar.py                # Bağımsız aralıklı tekrar CLI aracı
backend/
  auth.py                # Kayıt, giriş, e-posta doğrulama, şifre sıfırlama
  billing.py             # Ödeme ve abonelik yönetimi
  newsletter.py          # Bülten aboneliği
  support.py             # Destek talepleri
  cache.py               # TTL cache (scan/stock/news)
  calendar_api.py        # Google Calendar API entegrasyonu
  config.py              # Ortam değişkenleri ve sabitler
  data_fetcher.py        # yfinance batch OHLCV indirme
  db.py                  # SQLAlchemy + Flask-Migrate
  email.py               # İşlemsel e-posta gönderimi
  limits.py              # Plan tanımları ve gating decorator'lar
  models.py              # User, Watchlist, Portfolio, StockComment
  news.py                # RSS haber toplayıcı
  patterns.py            # Formasyon tespiti v2 + otomatik trend çizgileri
  quota_store.py         # Günlük kullanım sayacı (in-memory / Redis)
  repetition.py          # Aralıklı tekrar zamanlama mantığı
  scanner.py             # Tarama orkestrasyonu
  scoring.py             # Kesişim bazlı 10 puanlık sinyal motoru
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
| `GET /api/stock/<symbol>` | — | Hisse detayı, skor, 60g geçmiş, formasyonlar, trend çizgileri |
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
| `POST /api/repetition` | Auth | Aralıklı tekrar planı oluştur |
| `GET /api/health` | — | Sağlık kontrolü |
| `POST /api/cache/clear` | Admin | Tüm cache temizle |

## Auth API (`/auth`)

`/auth/signup` · `/auth/login` · `/auth/logout` · `/auth/me` · `/auth/forgot` · `/auth/reset` · `/auth/verify` · `/auth/resend-verify` · `/auth/export` · `/auth/consent`

## Notlar

- Yatırım tavsiyesi değildir, eğitim amaçlıdır.
- İlk istek uzun sürebilir (yfinance tüm hisseleri indirir). Sonraki yanıtlar önbellekten döner.
