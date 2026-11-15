"""AI destekli kullanıcı destek chatbot'u ve geri bildirim endpoint'i — Groq (Llama 3.3) ile."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request
from flask_login import current_user

from .db import db
from .models import Feedback
from .security import limiter

logger = logging.getLogger(__name__)

support_bp = Blueprint("support", __name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

SYSTEM_PROMPT = """Sen Nebula Scanner'ın Türkçe konuşan yardım asistanısın.
Kullanıcıların site hakkındaki sorularını yanıtlarsın ve sorunlarını çözmeye çalışırsın.
Kısa, net ve dostane yanıtlar ver. Teknik jargon kullanma.

## Nebula Scanner Hakkında

**Ne yapar?**
Nebula Scanner, BIST (Borsa İstanbul) ve ABD hisse senetlerini teknik analiz göstergeleriyle 0-10 arası puanlar.
Hisseler EMA trend hizalaması, RSI, MACD, Bollinger Bantları, ADX ve hacim gibi göstergelerle değerlendirilir.
Puan ne kadar yüksekse, teknik görünüm o kadar olumlu demektir. Bu bir yatırım tavsiyesi değildir.

**Üyelik**
- Misafir (kayıtsız): BIST'te 30 hisse görüntüleyebilir
- Üye (kayıtlı, ücretsiz): BIST'te tüm hisseler, ABD hisseleri, hisse detayları, alarm kurma, portföy, favoriler

Kayıt olmak tamamen ücretsizdir. Sağ üstten "Üye Ol" düğmesine tıklayarak kayıt olabilirsiniz.

**Tarama nasıl çalışır?**
Ana sayfada BIST veya US pazarını seçin. Hisseler puana göre sıralanır (10 = en iyi teknik görünüm).
Filtreleme çubuğundan "≥ 5 Puan", "≥ 7 Puan" veya "≥ 9 Puan" seçebilir, "Sırala" menüsüyle günlük/haftalık/aylık değişime göre dizebilirsiniz.
Hisse sembolüne göre arama yapmak için arama kutusunu kullanın. Puanın nasıl hesaplandığı "Rehber" sayfasında anlatılır.

**Hisse detayı**
Herhangi bir hisse kartına tıklayınca detay modalı açılır:
- Mum grafiği, destek/direnç seviyeleri ve otomatik trend çizgileri
- Teknik göstergeler (EMA, RSI, MACD, Bollinger, ADX, hacim)
- Haber akışı ve yapay zekâ destekli bilanço özeti
- Teknik formasyonlar (omuz-baş-omuz, ikili dip/tepe, üçgen, bayrak vb.)
Hisse detayı yalnızca üyelere açıktır (üyelik ücretsiz).

**Alarm kurma**
"Alarmlar" sekmesine gidin → "+ Yeni Alarm" düğmesine tıklayın.
Hisse sembolünü girin, "fiyat şu değerin üstüne çıkınca" ya da "altına düşünce" seçip hedef fiyatı yazın → "Alarm Kur".
Yalnızca fiyat alarmı vardır (RSI/MACD gibi gösterge alarmı yoktur). Alarm kurmak için e-posta adresinizin doğrulanmış olması gerekir.
Alarmlar borsa açıkken yaklaşık 5 dakikada bir kontrol edilir; tetiklenince e-posta gelir ve sitede bildirim görünür.

**Portföy takibi**
"Portföy" sekmesinden hisse ekleyebilir, alış fiyatı ve miktarı girebilirsiniz.
Portföyünüzün toplam değeri ve kar/zarar hesaplanır.

**Favoriler (Watchlist)**
Hisse kartının sağ üstündeki ★ yıldıza tıklayarak favorilere ekleyebilirsiniz.
"Favoriler" filtresiyle yalnızca favori hisselerinizi görebilirsiniz.

**Sık karşılaşılan sorunlar**

*Giriş yapamıyorum:*
- E-posta ve şifrenizi kontrol edin
- Şifrenizi unuttuysanız "Şifremi unuttum" bağlantısına tıklayın
- Hesabınız yoksa "Üye Ol"a tıklayın

*Kayıt olamıyorum:*
- Şifre en az 10 karakter olmalı, harf ve rakam içermeli
- KVKK onay kutucuğunu işaretlemeniz gerekiyor
- E-posta adresi geçerli olmalı

*Hisse verileri yüklenmiyor:*
- Sayfayı yenileyin (F5)
- Sağ üstteki ↻ yenile düğmesine tıklayın
- Veri sağlayıcısı geçici olarak meşgul olabilir, birkaç dakika sonra tekrar deneyin

*Alarm çalışmıyor:*
- Alarmın "Aktif" durumda olduğunu kontrol edin
- E-posta adresinizi doğru girdiğinizden emin olun
- Spam klasörünüzü kontrol edin

**Önemli not**
Nebula Scanner yatırım tavsiyesi vermez. Tüm puanlar ve analizler eğitim amaçlıdır.
Yatırım kararları için SPK lisanslı bir kuruluşa danışmanızı öneririz.

---
Kullanıcının sorusunu yukarıdaki bilgilere dayanarak yanıtla.
Eğer soruyu yanıtlayamıyorsan veya teknik bir sorunla karşılaştıysa, şunu söyle:
"Bu konuda sana yardımcı olamıyorum. Lütfen destek ekibimize e-posta gönderin — yanıt vermek için burada olacağız."
"""


@support_bp.route("/api/support/chat", methods=["POST"])
@limiter.limit("8 per minute; 60 per day")
def chat():
    if not GROQ_API_KEY:
        return jsonify({"error": "config_error", "message": "Destek servisi şu an kullanılamıyor."}), 503

    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message") or "").strip()
    history = data.get("history")
    if not isinstance(history, list):
        history = []

    if not user_message:
        return jsonify({"error": "bad_request", "message": "Mesaj boş olamaz."}), 400
    if len(user_message) > 1000:
        return jsonify({"error": "bad_request", "message": "Mesaj çok uzun (max 1000 karakter)."}), 400

    safe_history = []
    for turn in history[-10:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = str(turn.get("content") or "")[:500]
        if role in ("user", "assistant") and content:
            safe_history.append({"role": role, "content": content})

    safe_history.append({"role": "user", "content": user_message})

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=512,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + safe_history,
        )
        reply = response.choices[0].message.content
    except Exception:
        logger.exception("Groq API hatası")
        return jsonify({"error": "ai_error", "message": "Şu an yanıt veremiyorum, lütfen daha sonra tekrar deneyin."}), 503

    needs_escalation = any(phrase in reply for phrase in [
        "e-posta gönderin", "destek ekibimize", "yardımcı olamıyorum",
    ])

    return jsonify({"reply": reply, "needs_escalation": needs_escalation})


_VALID_CATEGORIES = {"genel", "hata", "oneri", "diger"}


@support_bp.route("/api/feedback", methods=["POST"])
@limiter.limit("5 per hour")
def submit_feedback():
    data = request.get_json(silent=True) or {}
    category = str(data.get("category") or "genel").strip().lower()
    message = str(data.get("message") or "").strip()
    user_email = str(data.get("email") or "").strip()[:200]

    if not message:
        return jsonify({"error": "bad_request", "message": "Mesaj boş olamaz."}), 400
    if len(message) > 2000:
        return jsonify({"error": "bad_request", "message": "Mesaj çok uzun (max 2000 karakter)."}), 400
    if category not in _VALID_CATEGORIES:
        category = "genel"

    # Giriş yapmış kullanıcıda e-postayı oturumdan al (istemcinin gönderdiğine güvenme).
    if current_user.is_authenticated:
        user_email = current_user.email

    # Veritabanına yazılır (eskiden /tmp/feedback.json — her deploy'da siliniyor
    # ve kimse okuyamıyordu). Admin: GET /api/admin/feedback
    try:
        db.session.add(Feedback(category=category, message=message, email=user_email or None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Geri bildirim kaydedilemedi")
        return jsonify({"error": "server_error", "message": "Geri bildirim kaydedilemedi."}), 500

    return jsonify({"ok": True})
