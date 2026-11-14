"""gunicorn ayarları — çalışma dizinindeki bu dosya otomatik yüklenir.

Tek süreç + thread: pandas/numpy/yfinance ve bellek önbellekleri tek kopya
tutulur (Railway RAM maliyeti), önbellek/kota/rate-limit sayaçları da tutarlı
olur. İş yükü ağırlıklı G/Ç (yfinance, DB) olduğu için thread'ler yeterlidir.

Not: komut satırı bayrakları bu dosyayı ezer. Railway'de özel bir başlatma
komutu (`--workers 2` gibi) tanımlıysa temizlenmelidir.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = 120
graceful_timeout = 30
accesslog = "-"


def post_worker_init(worker):
    """Uygulama yüklendikten sonra, worker sürecinin içinde: zamanlayıcıyı başlat.

    Bu kanca yalnızca gunicorn tarafından çağrılır; flask CLI, pytest ve
    `python -m backend.worker` altında zamanlayıcı kendiliğinden başlamaz.
    """
    try:
        from app import app as flask_app
        from backend import scheduler

        scheduler.start(flask_app)
    except Exception:  # zamanlayıcı başlamasa da site ayakta kalsın
        worker.log.exception("scheduler başlatılamadı")


def worker_exit(server, worker):
    try:
        from backend import scheduler

        scheduler.stop()
    except Exception:
        pass
