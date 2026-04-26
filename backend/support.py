"""AI destekli kullanıcı destek chatbot'u — Claude Haiku ile."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

support_bp = Blueprint("support", __name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """Sen Nebula Scanner'ın Türkçe konuşan yardım asistanısın.
Kullanıcıların site hakkındaki sorularını yanıtlarsın ve sorunlarını çözmeye çalışırsın.
Kısa, net ve dostane yanıtlar ver. Teknik jargon kullanma.

## Nebula Scanner Hakkında

**Ne yapar?**
Nebula Scanner, BIST (Borsa İstanbul) ve ABD hisse senetlerini teknik analiz göstergeleriyle 0-5 arası puanlar.
Hisseler RSI, MACD, Bollinger Bantları, hacim ve fiyat momentum gibi göstergeler kullanılarak değerlendirilir.
Puan ne kadar yüksekse, teknik görünüm o kadar olumlu demektir. Bu bir yatırım tavsiyesi değildir.

**Üyelik**
- Misafir (kayıtsız): BIST'te 30 hisse görüntüleyebilir
- Üye (kayıtlı, ücretsiz): BIST'te tüm hisseler, ABD hisseleri, hisse detayları, alarm kurma, portföy, favoriler

Kayıt olmak tamamen ücretsizdir. Sağ üstten "Üye Ol" düğmesine tıklayarak kayıt olabilirsiniz.

**Tarama nasıl çalışır?**
Ana sayfada BIST veya US sekmesini seçin. Hisseler puana göre sıralanır (5 = en iyi teknik görünüm).
Filtreleme çubuğundan "≥ 3 Puan", "≥ 4 Puan" veya "Sadece 5/5" seçebilirsiniz.
Hisse adına göre arama yapmak için arama kutusunu kullanın.

**Hisse detayı**
Herhangi bir hisse kartına tıklayınca detay modalı açılır:
- Fiyat grafiği (günlük/haftalık/aylık)
- Teknik göstergeler (RSI, MACD, Bollinger, hacim)
- Haber akışı
- Teknik formasyonlar (baş-omuz, çift dip, vb.)

**Alarm kurma**
"Alarmlar" sekmesine gidin → "+ Yeni Alarm" düğmesine tıklayın.
Hisse sembolü, kriter (örn. RSI 30'un altı, fiyat belirli seviyenin üstü) seçin → "Alarm Kur".
Alarm tetiklendiğinde e-posta ile bildirim alırsınız.

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
def chat():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "config_error", "message": "Destek servisi şu an kullanılamıyor."}), 503

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not user_message:
        return jsonify({"error": "bad_request", "message": "Mesaj boş olamaz."}), 400
    if len(user_message) > 1000:
        return jsonify({"error": "bad_request", "message": "Mesaj çok uzun (max 1000 karakter)."}), 400

    # Son 10 mesajı tut (context window tasarrufu)
    safe_history = []
    for turn in history[-10:]:
        role = turn.get("role")
        content = str(turn.get("content") or "")[:500]
        if role in ("user", "assistant") and content:
            safe_history.append({"role": role, "content": content})

    safe_history.append({"role": "user", "content": user_message})

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=safe_history,
        )
        reply = response.content[0].text
    except Exception as exc:
        logger.exception("Claude API hatası")
        return jsonify({"error": "ai_error", "message": "Şu an yanıt veremiyorum, lütfen daha sonra tekrar deneyin."}), 503

    needs_escalation = any(phrase in reply for phrase in [
        "e-posta gönderin", "destek ekibimize", "yardımcı olamıyorum",
    ])

    return jsonify({"reply": reply, "needs_escalation": needs_escalation})
