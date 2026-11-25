"""2.3.0 — Gelişmiş filtre (fiyat aralığı, tarih, dükkan, durum işaretleri) + kayıtlı filtreler,
garanti / son kullanma durumu. Arayüzden bağımsız (testlerde de kullanılır); telefonda aynısı ek230.js içinde."""
import json
from datetime import date, datetime

from .db import is_receipt, norm, term_in

WARN_DAYS = 30          # garanti / son kullanma için varsayılan uyarı süresi (gün)
SAVED_KEY = "saved_filters_v1"

# durum işaretleri: (anahtar, Türkçe etiket)
FLAGS = [
    ("photo", "Fotoğrafı olanlar"),
    ("nophoto", "Fotoğrafı olmayanlar"),
    ("receipt", "Faturası / fişi olanlar"),
    ("noprice", "Fiyatı girilmemiş"),
    ("loan", "Ödünçtekiler"),
    ("late", "Ödünç dönüşü gecikenler"),
    ("low", "Az kalanlar"),
    ("tobuy", "Alışveriş listesindekiler"),
    ("warranty", "Garantisi devam edenler"),
    ("warranty_soon", "Garantisi yakında bitecekler"),
    ("warranty_over", "Garantisi bitmiş olanlar"),
    ("exp_soon", "Son kullanma tarihi yaklaşanlar"),
    ("expired", "Son kullanma tarihi geçmiş olanlar"),
]


def _today(today=None):
    if isinstance(today, date):
        return today
    if today:
        return datetime.strptime(str(today)[:10], "%Y-%m-%d").date()
    return date.today()


def days_left(day, today=None):
    """Tarihe kalan gün (geçmişse eksi); tarih yoksa None."""
    try:
        d = datetime.strptime(str(day or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (d - _today(today)).days


def day_status(day, today=None, days=WARN_DAYS):
    """None (tarih yok) · 'ok' · 'soon' (≤ days gün kaldı) · 'over' (geçti)."""
    n = days_left(day, today)
    if n is None:
        return None
    if n < 0:
        return "over"
    return "soon" if n <= days else "ok"


def empty():
    return {"price_min": None, "price_max": None, "currency": "", "qty_min": None, "qty_max": None,
            "date_from": "", "date_to": "", "shop": "", "flags": []}


def clean(f):
    """Gelen filtreyi (kayıtlı, JSON) güvenli biçime getirir."""
    out = empty()
    if not isinstance(f, dict):
        return out
    for k in ("price_min", "price_max"):
        try:
            out[k] = None if f.get(k) in (None, "") else float(f[k])
        except (TypeError, ValueError):
            pass
    for k in ("qty_min", "qty_max"):
        try:
            out[k] = None if f.get(k) in (None, "") else int(f[k])
        except (TypeError, ValueError):
            pass
    for k in ("currency", "date_from", "date_to", "shop"):
        out[k] = str(f.get(k) or "").strip()
    known = {k for k, _ in FLAGS}
    out["flags"] = [x for x in (f.get("flags") or []) if x in known]
    return out


def is_active(f):
    f = clean(f)
    return any(f[k] not in (None, "", []) for k in f)


def count_active(f):
    f = clean(f)
    n = sum(1 for k in ("currency", "date_from", "date_to", "shop") if f[k])
    n += (f["price_min"] is not None or f["price_max"] is not None) + (f["qty_min"] is not None or f["qty_max"] is not None)
    return n + len(f["flags"])


def _overdue(d, today):
    n = days_left(d.get("loan_due"), today)
    return bool(d.get("loan_to")) and n is not None and n < 0


def _is_low(d):
    return int(d.get("min_qty") or 0) > 0 and int(d.get("quantity") or 0) < int(d.get("min_qty") or 0)


def match(d, f, today=None, days=WARN_DAYS):
    """Eşya (list_items / get_item biçimi) filtreye uyuyor mu? Bütün koşullar birlikte (VE) aranır."""
    f = clean(f)
    price = d.get("price")
    if f["currency"] and (price is None or d.get("currency") != f["currency"]):
        return False
    if f["price_min"] is not None and (price is None or price < f["price_min"]):
        return False
    if f["price_max"] is not None and (price is None or price > f["price_max"]):
        return False
    q = int(d.get("quantity") or 0)
    if f["qty_min"] is not None and q < f["qty_min"]:
        return False
    if f["qty_max"] is not None and q > f["qty_max"]:
        return False
    created = str(d.get("created_at") or "")[:10]
    if f["date_from"] and created < f["date_from"]:
        return False
    if f["date_to"] and created > f["date_to"]:
        return False
    if f["shop"]:
        hay = norm(" ".join(str(d.get(k) or "") for k in ("shop_name", "shop_place", "shop_phone")))
        if not all(term_in(t, hay) for t in norm(f["shop"]).split()):
            return False
    photos = d.get("photos")
    if photos is not None:
        n_photo = len([p for p in photos if not is_receipt(p)])
        n_rec = len([p for p in photos if is_receipt(p)]) + len(d.get("receipts") or [])
    else:
        n_photo, n_rec = int(d.get("photo_count") or 0), int(d.get("receipt_count") or 0)
    w, e = day_status(d.get("warranty_until"), today, days), day_status(d.get("expires_on"), today, days)
    checks = {
        "photo": n_photo > 0, "nophoto": n_photo == 0, "receipt": n_rec > 0, "noprice": price is None,
        "loan": bool(d.get("loan_to")), "late": _overdue(d, today), "low": _is_low(d),
        "tobuy": bool(d.get("to_buy")) or _is_low(d),
        "warranty": w in ("ok", "soon"), "warranty_soon": w == "soon", "warranty_over": w == "over",
        "exp_soon": e == "soon", "expired": e == "over",
    }
    return all(checks.get(x, True) for x in f["flags"])


def apply(items, f, today=None, days=WARN_DAYS):
    if not is_active(f):
        return list(items)
    return [d for d in items if match(d, f, today, days)]


# ------------------------------------------------------------------ kayıtlı filtreler
def saved(db):
    try:
        v = json.loads(db.get_setting(SAVED_KEY, "[]") or "[]")
        return [{"name": str(x["name"]), "f": clean(x.get("f"))} for x in v if isinstance(x, dict) and x.get("name")]
    except (ValueError, KeyError, TypeError):
        return []


def save(db, name, f):
    name = str(name or "").strip()[:60]
    if not name:
        return
    lst = [x for x in saved(db) if x["name"] != name]
    lst.append({"name": name, "f": clean(f)})
    db.set_setting(SAVED_KEY, json.dumps(lst[-30:], ensure_ascii=False))


def remove(db, name):
    db.set_setting(SAVED_KEY, json.dumps([x for x in saved(db) if x["name"] != name], ensure_ascii=False))


# ------------------------------------------------------------------ hatırlatmalar
def reminders(items, today=None, days=WARN_DAYS):
    """Garantisi / son kullanması yaklaşan ya da geçen eşyalar: [(eşya, tür, kalan gün)] (en acil önce)."""
    out = []
    for d in items:
        for kind, field in (("warranty", "warranty_until"), ("expiry", "expires_on")):
            st = day_status(d.get(field), today, days)
            if st in ("soon", "over"):
                n = days_left(d.get(field), today)
                if kind == "warranty" and n < -days:
                    continue          # garantisi çoktan bitmiş olanlar her gün hatırlatılmaz
                out.append((d, kind, n))
    return sorted(out, key=lambda x: x[2])
