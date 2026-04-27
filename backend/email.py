"""Transactional mail gönderimi — SMTP (Gmail vb.) veya Resend API.

Öncelik: SMTP_HOST varsa SMTP, yoksa RESEND_API_KEY varsa Resend, yoksa stdout log.
Config her çağrıda os.environ'dan okunur — Railway env var değişince redeploy yeterli.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from .config import APP_BASE_URL, EMAIL_FROM

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def _cfg():
    """Her çağrıda güncel env değerlerini döner (Railway yeniden deploy sonrası çalışır)."""
    return {
        "smtp_host": os.environ.get("SMTP_HOST", ""),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
        "smtp_user": os.environ.get("SMTP_USER", ""),
        "smtp_pass": os.environ.get("SMTP_PASS", ""),
        "resend_key": os.environ.get("RESEND_API_KEY", ""),
    }


def _send(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    cfg = _cfg()
    if cfg["smtp_host"] and cfg["smtp_user"] and cfg["smtp_pass"]:
        logger.info("E-posta SMTP üzerinden gönderiliyor: %s → %s", cfg["smtp_user"], to)
        return _send_smtp(to, subject, html, text, cfg)
    if cfg["resend_key"]:
        logger.info("E-posta Resend üzerinden gönderiliyor → %s", to)
        return _send_resend(to, subject, html, text, cfg["resend_key"])
    logger.warning("[DEV-EMAIL - SMTP/RESEND YAPILANDIRILMADI] To=%s | %s\n%s", to, subject, text or html)
    return True


def _send_smtp(to: str, subject: str, html: str, text: Optional[str], cfg: dict) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.sendmail(cfg["smtp_user"], [to], msg.as_bytes())
        logger.info("SMTP gönderimi başarılı → %s", to)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP kimlik doğrulama hatası (App Password kontrol et): %s", exc)
        return False
    except Exception as exc:
        logger.exception("SMTP gönderimi başarısız: %s", exc)
        return False


def _send_resend(to: str, subject: str, html: str, text: Optional[str], api_key: str) -> bool:
    try:
        r = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
                **({"text": text} if text else {}),
            },
            timeout=10,
        )
        if r.status_code >= 300:
            logger.error("Resend hata %s: %s", r.status_code, r.text)
            return False
        logger.info("Resend gönderimi başarılı → %s", to)
        return True
    except requests.RequestException as exc:
        logger.exception("Resend gönderilemedi: %s", exc)
        return False


def send_verify_email(to: str, token: str) -> bool:
    link = f"{APP_BASE_URL}/api/auth/verify?token={token}"
    subject = "Nebula Scanner — E-posta doğrulama"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#111;">
      <h2 style="margin-top:0;">Hoş geldin!</h2>
      <p>Nebula Scanner hesabını doğrulamak için aşağıdaki butona tıkla.</p>
      <p style="text-align:center;margin:32px 0;">
        <a href="{link}" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">E-postamı doğrula</a>
      </p>
      <p style="color:#666;font-size:13px;">Buton çalışmazsa bu bağlantıyı tarayıcına yapıştır:<br/><a href="{link}">{link}</a></p>
      <p style="color:#999;font-size:12px;margin-top:32px;">Bu maili sen istemediysen yok say. Bağlantı 24 saat geçerli.</p>
    </div>
    """
    text = f"E-postanı doğrulamak için: {link}\n\nBağlantı 24 saat geçerlidir."
    return _send(to, subject, html, text)


def send_password_reset(to: str, token: str) -> bool:
    link = f"{APP_BASE_URL}/?reset_token={token}"
    subject = "Nebula Scanner — Şifre sıfırlama"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#111;">
      <h2 style="margin-top:0;">Şifre sıfırlama</h2>
      <p>Aşağıdaki bağlantıyla yeni bir şifre belirleyebilirsin.</p>
      <p style="text-align:center;margin:32px 0;">
        <a href="{link}" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">Şifremi sıfırla</a>
      </p>
      <p style="color:#666;font-size:13px;"><a href="{link}">{link}</a></p>
      <p style="color:#999;font-size:12px;margin-top:32px;">Bu isteği sen yapmadıysan yok say. Bağlantı 1 saat geçerli.</p>
    </div>
    """
    text = f"Şifre sıfırlama bağlantın: {link}\n\nBağlantı 1 saat geçerlidir."
    return _send(to, subject, html, text)


def send_alert_triggered(to: str, symbol: str, label: str) -> bool:
    subject = f"Alarm: {symbol} — {label}"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#111;">
      <h2 style="margin-top:0;">{symbol}</h2>
      <p>Belirlediğin alarm tetiklendi:</p>
      <p style="background:#f3f4f6;padding:12px 16px;border-radius:8px;font-weight:600;">{label}</p>
      <p style="text-align:center;margin:32px 0;">
        <a href="{APP_BASE_URL}/?focus={symbol}" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">Hisse detayını aç</a>
      </p>
      <p style="color:#999;font-size:12px;margin-top:32px;">
        Bu bilgi yatırım tavsiyesi değildir. Eğitim ve bilgilendirme amaçlıdır.
      </p>
    </div>
    """
    text = f"{symbol} için alarm tetiklendi: {label}\n\n{APP_BASE_URL}/?focus={symbol}"
    return _send(to, subject, html, text)


def send_payment_failed(to: str) -> bool:
    link = f"{APP_BASE_URL}/account"
    subject = "Nebula Scanner — Ödeme başarısız"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#111;">
      <h2 style="margin-top:0;">Ödeme başarısız</h2>
      <p>Premium aboneliğin için yapılan ödeme tamamlanamadı. Premium özelliklere kesintisiz erişim için kart bilgilerini güncelle.</p>
      <p style="text-align:center;margin:32px 0;">
        <a href="{link}" style="background:#ef4444;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">Kartımı güncelle</a>
      </p>
    </div>
    """
    text = f"Premium ödemen başarısız oldu. Kartını güncelle: {link}"
    return _send(to, subject, html, text)
