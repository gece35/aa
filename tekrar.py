#!/usr/bin/env python3
"""Aralıklı tekrar (spaced repetition) ders takip aracı.

Kullanım:
    python tekrar.py ekle "Matematik" "Türev"
    python tekrar.py tablo
    python tekrar.py bugun
    python tekrar.py sil 3
    python tekrar.py ics
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "tekrar.db"
ICS_PATH = Path(__file__).parent / "ders_tekrar.ics"

ARALIKLAR = [
    ("1 gün", 1),
    ("1 hafta", 7),
    ("1 ay", 30),
    ("3 ay", 90),
]

HATIRLATMA_SAATI = 9  # 09:00'da telefona bildirim

RESET = "\033[0m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
GRAY = "\033[90m"
BOLD = "\033[1m"
CYAN = "\033[96m"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dersler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders TEXT NOT NULL,
            konu TEXT NOT NULL,
            eklenme_tarihi DATE NOT NULL,
            tekrar_1gun DATE NOT NULL,
            tekrar_1hafta DATE NOT NULL,
            tekrar_1ay DATE NOT NULL,
            tekrar_3ay DATE NOT NULL,
            uid TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def ekle(ders: str, konu: str) -> None:
    bugun = date.today()
    tarihler = [bugun + timedelta(days=d) for _, d in ARALIKLAR]
    uid = str(uuid.uuid4())
    conn = db()
    cur = conn.execute(
        """
        INSERT INTO dersler (ders, konu, eklenme_tarihi,
                             tekrar_1gun, tekrar_1hafta, tekrar_1ay, tekrar_3ay, uid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ders, konu, bugun.isoformat(), *[t.isoformat() for t in tarihler], uid),
    )
    conn.commit()
    yeni_id = cur.lastrowid
    conn.close()

    print(f"{GREEN}✓ Eklendi{RESET} (#{yeni_id})  {BOLD}{ders}{RESET} — {konu}")
    print(f"  Eklenme tarihi: {bugun.strftime('%d %b %Y')}")
    for (etiket, _), t in zip(ARALIKLAR, tarihler):
        print(f"  {etiket:8s} sonra → {t.strftime('%d %b %Y (%a)')}")
    ics_guncelle()
    print(f"\n{CYAN}ics güncellendi:{RESET} {ICS_PATH}")
    print(f"{GRAY}Bu dosyayı telefonunun Takvim uygulamasına aktar → bildirimler otomatik düşer.{RESET}")


def sil(row_id: int) -> None:
    conn = db()
    cur = conn.execute("DELETE FROM dersler WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"{GREEN}✓ #{row_id} silindi{RESET}")
        ics_guncelle()
    else:
        print(f"{RED}#{row_id} bulunamadı{RESET}")


def _renk(hedef: date, bugun: date) -> str:
    fark = (hedef - bugun).days
    if fark < 0:
        return RED
    if fark == 0:
        return YELLOW + BOLD
    if fark <= 3:
        return GREEN
    return GRAY


def _durum(hedef: date, bugun: date) -> str:
    fark = (hedef - bugun).days
    if fark < 0:
        return f"{abs(fark)} gün gecikti"
    if fark == 0:
        return "BUGÜN"
    if fark == 1:
        return "yarın"
    return f"{fark} gün sonra"


def tablo() -> None:
    conn = db()
    rows = conn.execute(
        "SELECT * FROM dersler ORDER BY eklenme_tarihi DESC, id DESC"
    ).fetchall()
    conn.close()

    if not rows:
        print(f"{GRAY}Henüz ders eklenmemiş. 'python tekrar.py ekle \"Ders\" \"Konu\"' ile başla.{RESET}")
        return

    bugun = date.today()
    print(f"\n{BOLD}{'ID':>3}  {'Ders':15s} {'Konu':25s} {'Eklendi':11s} {'1 gün':14s} {'1 hafta':14s} {'1 ay':14s} {'3 ay':14s}{RESET}")
    print(GRAY + "─" * 115 + RESET)
    for r in rows:
        hucreler = []
        for alan in ("tekrar_1gun", "tekrar_1hafta", "tekrar_1ay", "tekrar_3ay"):
            t = date.fromisoformat(r[alan])
            renk = _renk(t, bugun)
            hucreler.append(f"{renk}{t.strftime('%d %b')} {_durum(t, bugun)[:6]:6s}{RESET}")
        eklendi = date.fromisoformat(r["eklenme_tarihi"]).strftime("%d %b %Y")
        ders = r["ders"][:14]
        konu = r["konu"][:24]
        print(f"{r['id']:>3}  {ders:15s} {konu:25s} {eklendi:11s} " + " ".join(h.ljust(14 + len(renk) + len(RESET)) for h in hucreler))


def bugun_gosterge() -> None:
    """Bugün ve önümüzdeki 7 gün içindeki tekrarları listele."""
    conn = db()
    rows = conn.execute("SELECT * FROM dersler").fetchall()
    conn.close()

    bugun = date.today()
    hedefler: list[tuple[date, str, str, str, int]] = []
    for r in rows:
        for (etiket, _), alan in zip(ARALIKLAR,
                                      ("tekrar_1gun", "tekrar_1hafta", "tekrar_1ay", "tekrar_3ay")):
            t = date.fromisoformat(r[alan])
            hedefler.append((t, r["ders"], r["konu"], etiket, r["id"]))

    hedefler.sort()
    geciken = [h for h in hedefler if h[0] < bugun]
    bugunkuler = [h for h in hedefler if h[0] == bugun]
    yaklasanlar = [h for h in hedefler if 0 < (h[0] - bugun).days <= 7]

    if geciken:
        print(f"\n{RED}{BOLD}⚠ Gecikmiş tekrarlar:{RESET}")
        for t, ders, konu, etiket, rid in geciken:
            print(f"  {RED}#{rid} {t.strftime('%d %b')}  {ders} — {konu}  ({etiket} tekrarı, {(bugun - t).days} gün gecikti){RESET}")

    if bugunkuler:
        print(f"\n{YELLOW}{BOLD}📚 Bugün tekrar:{RESET}")
        for t, ders, konu, etiket, rid in bugunkuler:
            print(f"  {YELLOW}#{rid} {ders} — {konu}  ({etiket} tekrarı){RESET}")
    else:
        print(f"\n{GRAY}Bugün tekrar yok.{RESET}")

    if yaklasanlar:
        print(f"\n{GREEN}{BOLD}Önümüzdeki 7 gün:{RESET}")
        for t, ders, konu, etiket, rid in yaklasanlar:
            gun = (t - bugun).days
            print(f"  {GREEN}#{rid} {t.strftime('%d %b (%a)')} (+{gun}g)  {ders} — {konu}  ({etiket}){RESET}")


def _ics_event(uid: str, baslik: str, aciklama: str, tarih: date) -> str:
    """09:00-09:30 arası tek etkinlik, etkinliğin başında alarm."""
    dt_start = datetime.combine(tarih, datetime.min.time()).replace(hour=HATIRLATMA_SAATI)
    dt_end = dt_start + timedelta(minutes=30)
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"SUMMARY:{_ics_escape(baslik)}\r\n"
        f"DESCRIPTION:{_ics_escape(aciklama)}\r\n"
        "BEGIN:VALARM\r\n"
        "ACTION:DISPLAY\r\n"
        f"DESCRIPTION:{_ics_escape(baslik)}\r\n"
        "TRIGGER:-PT0M\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
    )


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def ics_guncelle() -> None:
    conn = db()
    rows = conn.execute("SELECT * FROM dersler ORDER BY eklenme_tarihi").fetchall()
    conn.close()

    parcalar = [
        "BEGIN:VCALENDAR\r\n",
        "VERSION:2.0\r\n",
        "PRODID:-//Tekrar CLI//TR\r\n",
        "CALSCALE:GREGORIAN\r\n",
        "METHOD:PUBLISH\r\n",
        "X-WR-CALNAME:Ders Tekrarları\r\n",
        "X-WR-TIMEZONE:Europe/Istanbul\r\n",
    ]

    for r in rows:
        for (etiket, _), alan in zip(ARALIKLAR,
                                      ("tekrar_1gun", "tekrar_1hafta", "tekrar_1ay", "tekrar_3ay")):
            tarih = date.fromisoformat(r[alan])
            baslik = f"📚 {r['ders']} — {r['konu']} ({etiket} tekrarı)"
            aciklama = (
                f"Ders: {r['ders']}\n"
                f"Konu: {r['konu']}\n"
                f"Orijinal çalışma: {r['eklenme_tarihi']}\n"
                f"Tekrar aralığı: {etiket}"
            )
            uid = f"{r['uid']}-{alan}@tekrar"
            parcalar.append(_ics_event(uid, baslik, aciklama, tarih))

    parcalar.append("END:VCALENDAR\r\n")
    ICS_PATH.write_text("".join(parcalar), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Aralıklı tekrar ders takibi")
    sub = p.add_subparsers(dest="cmd")

    pe = sub.add_parser("ekle", help="Yeni ders ekle")
    pe.add_argument("ders")
    pe.add_argument("konu")

    sub.add_parser("tablo", help="Tüm dersleri ve tekrar tarihlerini göster")
    sub.add_parser("bugun", help="Bugünkü ve yaklaşan tekrarları göster")
    sub.add_parser("ics", help=".ics dosyasını yeniden üret")

    ps = sub.add_parser("sil", help="Kayıt sil")
    ps.add_argument("id", type=int)

    args = p.parse_args()

    if args.cmd == "ekle":
        ekle(args.ders, args.konu)
    elif args.cmd == "tablo":
        tablo()
    elif args.cmd == "bugun":
        bugun_gosterge()
    elif args.cmd == "sil":
        sil(args.id)
    elif args.cmd == "ics":
        ics_guncelle()
        print(f"{GREEN}✓{RESET} {ICS_PATH}")
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
