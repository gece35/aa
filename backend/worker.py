"""Eski worker giriş noktası.

Arka plan işleri (fiyat alarmı kontrolü, doğrulanmamış hesap temizliği) artık
web sürecinin içindeki zamanlayıcıda çalışır: bkz. backend/scheduler.py.
Ayrı bir worker servisine gerek kalmadı.

    python -m backend.worker          → hiçbir iş yapmaz, yalnızca bekler.
                                         (Railway'de unutulmuş bir worker servisi
                                         bu komutla çalışıyorsa uygulamayı
                                         yüklemez, çift iş yapmaz — servisi silin.)
    python -m backend.worker --once   → işleri seans saatine bakmadan bir kez
                                         çalıştırır (lokal test / elle tetikleme).

Bu modül bilerek yalnızca stdlib import eder: argümansız çalıştığında Flask,
pandas vb. belleğe yüklenmez.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

logger = logging.getLogger("backend.worker")


def run_once() -> dict:
    """Uygulamayı yükleyip zamanlayıcı işlerini tek sefer çalıştırır."""
    from app import app  # app.py modül düzeyinde create_app() çağırır
    from backend import scheduler
    from backend.db import db

    with app.app_context():
        try:
            return scheduler.run_due_jobs(force=True)
        finally:
            db.session.remove()


def _idle() -> None:
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.warning(
        "Bu worker servisi artık gerekli değil: arka plan işleri web sürecinde "
        "çalışıyor. Bu servisi Railway panelinden silebilirsiniz. (Bekleme modunda.)"
    )
    while not stop:
        time.sleep(5)


def main(argv=None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if "--once" in args:
        result = run_once()
        logger.info("worker --once sonucu: %s", result)
        return 0
    _idle()
    return 0


if __name__ == "__main__":
    sys.exit(main())
