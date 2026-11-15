# Nebula Scanner

BIST (162 hisse) ve ABD borsası (248 hisse) hisselerini **hibrit durum + kesişim tazeliği motoru** ile tarayan ve **0-10** arası puanlayan Flask + Vanilla JS uygulaması. Railway üzerinde canlıya alınmıştır (web + worker + Postgres).

## Puanlama Motoru (0-10) — hibrit durum + kesişim tazeliği

Tek vektörize motor (`backend/scoring.py` → `compute_score_frame`) hem canlı tarama hem backtest tarafından kullanılır (tek kaynak, sapma yok). Her bileşen piyasanın **mevcut durumunu** sürekli ölçer; kesişimler küçük bir tazelik bonusu ekler ama zorunlu değildir — bir hisse aktif kesişim olmadan da yüksek skor alabilir.

| Bileşen | Max Puan | Ne Ölçer? |
|---------|----------|-----------|
| **EMA Hizalama (trend)** | 2.0 | Fiyat > EMA30 > EMA50 > EMA200 hiyerarşisi (3 kademeli, eşit ağırlık) |
| **RSI Durumu** | 2.0 | Bölge skoru (50-65 ideal) + aşırı satımdan toparlanma bonusu |
| **MACD Pozisyon** | 1.5 | MACD > sinyal hattı + MACD > 0 + taze kesişim bonusu |
| **Bollinger Giriş** | 1.5 | Fiyatın alt banda yakınlığı (%B) + orta bandı yukarı kesme tazeliği |
| **ADX Güç** | 1.5 | Trend gücü (ADX seviyesi) + DI+ / DI− yön kesişimi |
| **MACD Histogram** | 1.0 | Histogram yönü + büyüme + sıfır kesişimi tazeliği |
| **Hacim Onayı** | 1.0 | Hacmin 20-gün ortalamasına göre spike'ı (bağımsız bonus) |
| **Genişleme Cezası** | −2.0 | 52 haftalık zirveye aşırı yakınlık + EMA20 sapma (gerçek kırılımda ceza %70 azalır) |

Ham toplam (maks ≈10.5) `EWM(span=2)` ile yumuşatılır ve 0-10'a clip edilir.

### Canlı Giriş Sinyali — "TDOV Eşleşti" rozeti

Tarama kartlarında bir hisse, `backend/backtest.py`'nin (bkz. aşağıda) olay-tabanlı giriş kurallarının **aynısını** karşılıyorsa 🎯 **TDOV Eşleşti** rozetiyle işaretlenir: taze boğa kesişimi + trend yönü onayı + skor ≥6 + trend alt-skoru ≥1.2 + hacim onayı + 52 hafta filtresi (ABD'de ek olarak göreli güç + çift kesişim şartı). Eşikler `scoring.py`'da tek kaynak olarak tanımlıdır, `backtest.py` bunları oradan import eder. Piyasa rejimi (endeks 200 günlük ortalamanın altındaysa) kapalıyken hiçbir hissede rozet gösterilmez — bu bilgi Tarama sekmesinin üstündeki BIST 100 / S&P 500 endeks kartlarında (`/api/index/<market>`) 🟢/🔴 durumuyla gösterilir. Rozet kasıtlı olarak nadir görünür; bu bir alım tavsiyesi değil, geçmiş test verisiyle örtüşme bilgisidir.

**Görünürlük:** Yatırım tavsiyesi izlenimini önlemek için rozet yalnızca `is_admin=True` olan hesaba gösterilir; `/api/scan` ve `/api/stock/<symbol>` yanıtlarında admin olmayan kullanıcılar için `entry_signal` sunucu tarafında `false`'a maskelenir (`app.py` → `_mask_entry_signal*`). Maskeleme, paylaşılan TTL cache'deki gerçek değeri bozmadan yalnızca yanıt kopyasında uygulanır.

## Formasyon Tespiti (`backend/patterns.py`) — v2

Son 120 barda 11 teknik formasyon türü tespiti; her formasyon için güven skoru, geçerlilik kontrolü ve işaretçi/trend çizgisi koordinatları üretilir.

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

- **Kısa vadeli** (son 60 bar, pivot penceresi 3, min. 2 temas): güncel fiyata en fazla **%7** uzaklıkta olabilir
- **Uzun vadeli** (son 200 bar, pivot penceresi 6, min. 3 temas, en az 60 bar geriden başlar): güncel fiyata en fazla **%15** uzaklıkta olabilir

Bir çizginin geçerli sayılması için hiçbir mum gövdesini delmemesi, güncel fiyattan kopuk olmaması ve mümkünse pencerenin trend yönüyle uyumlu eğimde olması gerekir (yükselen piyasada yükselen destek, düşen piyasada alçalan direnç — fiyattan kopuk "tarihi" çizgiler böylece elenir). Geçerli diyagonal çizgi yoksa en çok test edilmiş, kırılmamış **yatay** destek/direnç seviyesine düşülür; kısa vadede o da yoksa henüz kırılmamış **son swing dip/tepe** seviyesi kullanılır. Hiçbir şart sağlanmıyorsa çizgi hiç çizilmez.

## Mimari

Railway'de **tek servis, tek süreç**: `web` (gunicorn, 1 süreç × 8 thread — ayarlar `gunicorn.conf.py`). Ayrı worker servisi ve Redis yoktur; maliyet için bilinçli tercih.

- **Süreç içi zamanlayıcı** (`backend/scheduler.py`) — web sürecindeki tek bir thread; yalnızca seans saatlerinde (`backend/market_hours.py`) 5 dakikada bir tüm aktif alarm sembollerinin fiyatını tek toplu indirmeyle kontrol eder, günde bir doğrulanmamış hesapları temizler. Yalnızca gunicorn altında başlar. `python -m backend.worker --once` aynı işleri bir kez elle çalıştırır.
- **Açılışta otomatik migration** (`backend/migrate_boot.py`) — Railway `release` adımı çalıştırmadığı için şema açılışta güncellenir; `create_all` ile kurulmuş eski veritabanı doğru revizyona damgalanır. Durum `/api/health` yanıtında (`schema`, `migration`, `scheduler`) görünür.

- **Factory pattern Flask app** — `create_app()` ile oluşturulan tek uygulama
- **Postgres + SQLAlchemy** — üretimde Postgres (`psycopg`), Flask-Migrate ile şema geçmişi (`migrations/`); lokal geliştirmede SQLite fallback
- **Auth & abonelik** — Flask-Login ile oturum, e-posta doğrulama/şifre sıfırlama (`auth.py`); LemonSqueezy ile Premium abonelik (`billing.py`). İlk 100 kayıt ömür boyu ücretsiz Premium alır (`auth.py` → `signup`); sonrasında Premium, frontend'deki Ayarlar/Fiyatlandırma modallarından LemonSqueezy checkout ile satın alınır. Şu an Üye (ücretsiz) ve Premium arasında özellik farkı yok — bu ayrım ayrı bir iş olarak planlanıyor.
- **Rate limiting & günlük kota** — hassas auth uçları (login/signup/forgot/resend-verify/password) `Flask-Limiter` ile IP başına sınırlanır (`security.py`, süreç belleğinde); ayrıca özellik başı günlük kullanım kotası (`limits.py`, `quota_store.py`)
- **Güvenlik** — rate-limit anahtarı gerçek istemci IP'sidir (`CF-Connecting-IP`, bkz. `security.client_ip`); parola değişince/sıfırlanınca diğer oturumlar düşer (`User.get_id` parmak izi); `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS her yanıtta; `Content-Security-Policy` şimdilik Report-Only modda (`app.py`)
- **Toplu veri indirme** — `yfinance.download(..., threads=True)` ile tüm hisseler tek seferde
- **TTL + LRU cache** (`backend/cache.py`) — `/api/scan`, `/api/stock`, `/api/news`, `/api/index/<market>` yanıtları süreç belleğinde, kayıt üst sınırıyla önbelleklenir; seans açıkken kısa ömür (10 dk), pazar kapalıyken bir sonraki açılışa kadar; `force=1` bypass eder
- **Lexicon tabanlı sentiment** — Haber başlıklarını TR+EN kelime listesiyle pozitif/nötr/negatif sınıflandırır
- **AI destekli bilanço analizi** — Groq (Llama 3.3) ile temel analiz sağlığı sınıflandırması (`fundamentals.py`); ABD hisselerinde güvenilir, BIST'te çoğu zaman veri yok
- **Backtest motoru (TDOV)** — olay-tabanlı giriş (taze kesişim + trend onayı) + 3 aşamalı ATR trailing çıkış (`backtest.py`); canlı taramadaki "TDOV Eşleşti" rozeti aynı eşikleri kullanır (bkz. yukarı, `/rehber`)
- **Destek/Direnç seviyeleri** — Pivot tabanlı kümeleme ile `supports` / `resistances` + otomatik SL/TP hesabı
- **Monitoring** — Sentry entegrasyonu (opsiyonel, `SENTRY_DSN`)

## Aralıklı Tekrar Sistemi

Projeden bağımsız, ders takibi için komut satırı aracı (web sitesinin parçası değildir; sitedeki eski `/api/repetition/*` uçları kaldırıldı).

### CLI (`tekrar.py`)

```bash
python tekrar.py ekle "Matematik" "Türev"   # Ders ekle (1g/1h/1ay/3ay tekrar planı oluşturur)
python tekrar.py tablo                       # Tüm dersleri ve tekrar tarihlerini göster
python tekrar.py bugun                       # Bugünkü ve 7 gün içindeki tekrarları listele
python tekrar.py sil 3                       # Kayıt sil
python tekrar.py ics                         # .ics takvim dosyasını yeniden üret
```

Tekrar tarihleri: `+1 gün → +1 hafta → +1 ay → +3 ay`. `.ics` dosyası telefon takvimine aktarılabilir, 09:00'da otomatik alarm düşer.

## Klasör Yapısı

```
app.py                   # Flask giriş noktası (create_app factory)
tekrar.py                # Bağımsız aralıklı tekrar CLI aracı
backend/
  alerts.py              # Fiyat hedefi alarmları (SQLAlchemy) — üstüne çıkınca / altına düşünce
  auth.py                # Kayıt, giriş, e-posta doğrulama, şifre sıfırlama
  backtest.py            # TDOV backtest motoru (olay-tabanlı giriş/çıkış, ATR trailing)
  billing.py             # LemonSqueezy ödeme ve abonelik yönetimi
  newsletter.py          # Bülten: aboneler (DB), haftalık özet gönderimi, abonelikten çıkış
  support.py             # Destek talepleri
  cache.py               # Süreç içi TTL + LRU cache (scan/stock/news/index)
  config.py              # Ortam değişkenleri ve sabitler
  data_fetcher.py        # yfinance batch OHLCV indirme
  db.py                  # SQLAlchemy + Flask-Migrate
  email.py               # İşlemsel e-posta gönderimi
  fundamentals.py        # Groq AI ile bilanço/temel analiz
  limits.py              # Plan tanımları ve gating decorator'lar
  models.py              # User, Watchlist, Portfolio, StockComment
  news.py                # RSS haber toplayıcı
  patterns.py            # Formasyon tespiti v2 + otomatik trend çizgileri
  market_hours.py        # BIST/ABD seans saatleri (zamanlayıcı + cache ömrü)
  migrate_boot.py        # Açılışta otomatik şema bootstrap'ı (stamp + upgrade)
  quota_store.py         # Günlük kullanım sayacı (süreç belleği)
  scanner.py             # Tarama orkestrasyonu + endeks özeti
  scoring.py             # Hibrit durum + kesişim tazeliği puanlama motoru
  sectors.py             # Sektör etiketleri
  scheduler.py           # Süreç içi zamanlayıcı: fiyat alarmları + hesap temizliği
  security.py            # Parola/token, gerçek istemci IP'si, rate limiting
  seo.py                 # /hisse/<sembol>, /hisseler, dinamik /sitemap.xml
  sentiment.py           # Lexicon tabanlı haber duygu analizi
  tickers.py             # BIST (162) + US (248) sembol listeleri
  twitter_bot.py         # Twitter/X sinyal paylaşımı (şu an devre dışı, zamanlanmıyor)
  worker.py              # Eski worker girişi: bekleme modu / `--once` tek geçiş
frontend/
  index.html             # Ana tarayıcı arayüzü (glassmorphism / dark)
  rehber.html            # Kullanım kılavuzu
  about.html             # Hakkında
  faq.html               # Sıkça sorulan sorular
  blog/                  # Blog yazıları
  legal/                 # Gizlilik, kullanım koşulları
  app.js                 # Vanilla JS etkileşim
  style.css              # Koyu mod + galaksi + neon
templates/               # Jinja şablonları (hisse sayfaları, bülten çıkış sayfası)
migrations/              # Alembic (Flask-Migrate) veritabanı şema geçmişi
tests/                   # pytest paketi (python -m pytest)
gunicorn.conf.py         # Tek süreç + thread ayarı, zamanlayıcı kancası
requirements.txt         # Sabitlenmiş sürümler (requirements-dev.txt: + pytest)
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

## Haftalık bülten

Aboneler (`newsletter_subscribers` tablosu + pazarlama izni veren doğrulanmış üyeler) her Pazar 10:00'da (TSİ) BIST/ABD'nin en yüksek puanlı 10'ar hissesini içeren özet e-postasını alır. Gönderim **varsayılan kapalıdır**: `NEWSLETTER_ENABLED=1` ile açılır. Aynı sayı aynı kişiye iki kez gitmez (önce-sahiplen-sonra-gönder); günlük üst sınır `NEWSLETTER_DAILY_CAP` (varsayılan 250), kalanlar izleyen iki gün içinde gönderilir. Açmadan önce admin hesabıyla `POST /api/admin/newsletter/test` çağrılarak kendi adresinize deneme gönderilebilir.

## Tarama filtreleri ve CSV

Tarama sekmesindeki **Filtreler** paneli (sektör, RSI aralığı, günlük değişim, hacim patlaması, 52 hafta zirvesine yakın) tamamen tarayıcıda, yüklenmiş sonuçlar üzerinde çalışır ve seçimleri adres çubuğuna yazar (`?sektor=bank&rsi=50-70`), böylece süzülmüş liste bağlantıyla paylaşılabilir. **CSV** butonları görünen tarama listesini ve portföyü Türkçe Excel uyumlu (UTF-8 BOM, `;` ayraç) dosya olarak indirir.

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
| `GET /api/index/<market>` | — | Endeks özeti (BIST 100 / S&P 500) + rejim durumu + mini grafik verisi |
| `GET /api/scan?market=bist&force=0` | — | Tarama (skora göre sıralı, chunk'lı yüklenir) |
| `GET /api/stock/<symbol>` | Kota | Hisse detayı, skor, geçmiş, formasyonlar, trend çizgileri, SL/TP (misafir: IP başına günde 5, yalnız taranan hisseler) |
| `GET /api/stock/<symbol>/fundamentals` | — | AI destekli bilanço/temel analiz (Groq) |
| `GET /api/news?market=bist` | — | Piyasa haberleri + sentiment |
| `GET /api/news/stock/<symbol>` | — | Hisseye özel haberler |
| `GET /api/exchange-rate` | — | USD/TRY kuru |
| `GET /api/backtest?market=bist` | Admin | TDOV backtest sonuçları |
| `GET /api/signal-study?market=bist` | Admin | Kesişim türlerinin tarihsel isabet etüdü |
| `GET /api/alerts` | Auth | Alarmları listele |
| `POST /api/alerts` | Auth | Alarm oluştur |
| `DELETE /api/alerts/<id>` | Auth | Alarm sil |
| `POST /api/alerts/<id>/dismiss` | Auth | Tetiklenen alarmı kapat |
| `GET /api/alerts/triggered` | Auth | Tetiklenen alarmlar |
| `GET /api/alerts/conditions` | — | Desteklenen alarm kriter tipleri |
| `GET /api/watchlist` | Auth | İzleme listesi |
| `POST /api/watchlist` | Auth | Listeye ekle |
| `DELETE /api/watchlist/<symbol>` | Auth | Listeden çıkar |
| `GET /api/portfolio` | Auth | Portföy pozisyonları |
| `POST /api/portfolio` | Auth | Pozisyon ekle |
| `DELETE /api/portfolio/<id>` | Auth | Pozisyon sil |
| `GET /api/comments/<symbol>` | Auth | Topluluk yorumları |
| `POST /api/comments/<symbol>` | Auth | Yorum ekle |
| `DELETE /api/comments/<id>` | Auth | Yorum sil |
| `GET /api/config` | — | Ön yüz için ortam/konfig bilgisi (GA id, sektör etiketleri vb.) |
| `GET /hisse/<SEMBOL>` | — | Sunucuda render edilen, indekslenebilir hisse özeti (BIST'te `.IS` eksiz: `/hisse/THYAO`) |
| `GET /hisseler` · `/sitemap.xml` | — | Tüm hisselerin sektör dizini · dinamik sitemap (statik + blog + yasal + hisse sayfaları) |
| `GET/POST /newsletter/unsubscribe?token=` | — | Bülten aboneliğinden çıkış (GET onay sayfası, POST çıkış) |
| `GET /api/health` | — | Sağlık kontrolü: DB, şema revizyonu, zamanlayıcı durumu |
| `POST /api/cache/clear` | Admin | Tüm cache temizle |
| `GET /api/admin/stats` · `/api/admin/users` · `/api/admin/feedback` | Admin | Kullanıcı/istatistik paneli, geri bildirimler |
| `GET /api/admin/newsletter/preview` · `POST /api/admin/newsletter/test` | Admin | Haftalık bülten önizlemesi · yalnızca admin'e test gönderimi |

Ayrıca `/api/billing/*` (LemonSqueezy checkout/portal/webhook), `/api/newsletter`, `/api/newsletter/count`, `/api/support/chat`, `/api/feedback` blueprint'leri ve `/blog/`, `/faq`, `/legal/<slug>`, `/rehber`, `/about` statik sayfaları mevcuttur.

## Auth API (`/api/auth`)

`/api/auth/signup` · `/api/auth/login` · `/api/auth/logout` · `/api/auth/me` (`GET`/`DELETE`, silme şifre onayı ister) · `/api/auth/password` (şifre değiştir, oturum açıkken) · `/api/auth/forgot` · `/api/auth/reset` · `/api/auth/verify` · `/api/auth/resend-verify` · `/api/auth/resend-verify-public` · `/api/auth/export` · `/api/auth/consent`

## Notlar

- Yatırım tavsiyesi değildir, eğitim amaçlıdır.
- İlk istek uzun sürebilir (yfinance tüm hisseleri indirir). Sonraki yanıtlar önbellekten döner.
