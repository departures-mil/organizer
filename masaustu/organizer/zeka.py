"""2.3.0 — Yapay zeka (çevrim içi + çevrim dışı).

Çevrim içi: kullanıcının KENDİ anahtarıyla (Google Gemini · OpenAI · Anthropic Claude · Groq) — yöneticinin limitleri
kullanılmaz. Anahtar ortak çekirdeğin deposunda ('ai' = {provider, key, model}) durur; Ayarlar → Yapay zeka.
Çağrılar Kullanım Limitleri kartında sayılır (fccore.usage 'ai.<sağlayıcı>').
Çevrim dışı: internet ya da anahtar yoksa sorular cihazdaki kayıtlardan kurallarla cevaplanır."""
import base64
import json
import re
import urllib.error
import urllib.request

from .db import norm, parse_voice
from . import filtre

PROVIDERS = [
    # (anahtar, ad, metin modeli, görüntü modeli, anahtar alma adresi)
    ("gemini", "Google Gemini", "gemini-flash-latest", "gemini-flash-latest", "https://aistudio.google.com/apikey"),
    ("openai", "OpenAI", "gpt-4o-mini", "gpt-4o-mini", "https://platform.openai.com/api-keys"),
    ("anthropic", "Anthropic Claude", "claude-haiku-5-5", "claude-haiku-5-5", "https://console.anthropic.com/settings/keys"),
    ("groq", "Groq", "llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct", "https://console.groq.com/keys"),
]
LANG_NAMES = {"tr": "Türkçe", "en": "English", "ar": "العربية"}
TIMEOUT = 40


class AiError(Exception):
    """kind: 'nokey' · 'net' (internet yok) · 'auth' (anahtar geçersiz) · 'limit' · 'other'"""

    def __init__(self, kind, detail=""):
        super().__init__(detail or kind)
        self.kind, self.detail = kind, detail


# ------------------------------------------------------------------ ayar
def cfg():
    try:
        from fccore import storage
        a = storage.get("ai") or {}
    except Exception:
        a = {}
    if a.get("key") and a.get("provider") in [p[0] for p in PROVIDERS]:
        return {"provider": a["provider"], "key": str(a["key"]).strip(), "model": (a.get("model") or "").strip()}
    return None


def set_cfg(provider, key, model=""):
    from fccore import storage
    if not key:
        storage.set("ai", {"provider": provider or "gemini", "key": ""})
    else:
        storage.set("ai", {"provider": provider, "key": key.strip(), "model": (model or "").strip()})


def provider_info(pid):
    return next((p for p in PROVIDERS if p[0] == pid), PROVIDERS[0])


# ------------------------------------------------------------------ çağrı
def call(prompt, image=None, mime="image/jpeg", max_tokens=900, conf=None):
    """Sağlayıcıya tek bir istek gönderir, metin cevabı döndürür. image: bayt dizisi (isteğe bağlı)."""
    a = conf or cfg()
    if not a:
        raise AiError("nokey")
    pid, key = a["provider"], a["key"]
    info = provider_info(pid)
    model = a.get("model") or (info[3] if image else info[2])
    b64 = base64.b64encode(image).decode("ascii") if image else None
    h = {"Content-Type": "application/json"}
    if pid == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        parts = [{"text": prompt}]
        if b64:
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        body = {"contents": [{"parts": parts}], "generationConfig": {"maxOutputTokens": max_tokens}}

        def pick(j):
            return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
    elif pid == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        content = [{"type": "text", "text": prompt}]
        if b64:
            content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}

        def pick(j):
            return "".join(c.get("text", "") for c in j["content"] if c.get("type") == "text")
    else:
        url = "https://api.groq.com/openai/v1/chat/completions" if pid == "groq" else "https://api.openai.com/v1/chat/completions"
        h["Authorization"] = "Bearer " + key
        content = [{"type": "text", "text": prompt}]
        if b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content if b64 else prompt}]}

        def pick(j):
            return j["choices"][0]["message"]["content"]
    try:
        from fccore import usage
        usage.count("ai." + pid)
    except Exception:
        pass
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        kind = "auth" if e.code in (400, 401, 403) and re.search(r"key|auth|permission|API_KEY", detail, re.I) else \
            "limit" if e.code == 429 else "other"
        raise AiError(kind, f"HTTP {e.code} {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AiError("net", str(e)) from None
    try:
        return str(pick(j) or "").strip()
    except (KeyError, IndexError, TypeError):
        raise AiError("other", json.dumps(j)[:300]) from None


def _json_from(text):
    m = re.search(r"\{[\s\S]*\}", text or "")
    try:
        return json.loads(m.group(0) if m else text)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ eşyalar hakkında soru
def _context(items, limit=500):
    lines = []
    for d in items[:limit]:
        parts = [d["name"], f"x{d.get('quantity', 0)}"]
        if d.get("location_path"):
            parts.append("@" + d["location_path"])
        if d.get("category_path"):
            parts.append("#" + d["category_path"])
        if d.get("price") is not None:
            parts.append(f"{d['price']:g} {d.get('currency', '')}")
        if d.get("loan_to"):
            parts.append("loaned:" + d["loan_to"])
        if d.get("warranty_until"):
            parts.append("warranty:" + d["warranty_until"])
        if d.get("expires_on"):
            parts.append("expires:" + d["expires_on"])
        if d.get("shop_name"):
            parts.append("shop:" + d["shop_name"])
        if d.get("notes"):
            parts.append("note:" + d["notes"].replace("\n", " ")[:70])
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def ask_online(question, items, lang, today=""):
    p = ("You are the assistant inside a home inventory app called Organizer. Below is the user's item list "
         "(one item per line: name | xQuantity | @Location path | #Category | price | loan/warranty/expiry/shop/notes). "
         f"Today is {today}. Answer the user's question ONLY from this list, briefly and concretely (at most 8 short lines), "
         f"in {LANG_NAMES.get(lang, 'Türkçe')}. Always say WHERE an item is (its location path). If nothing matches, say so "
         "and suggest the closest items.\n\nITEMS:\n" + _context(items) + "\n\nQUESTION: " + question)
    return call(p, max_tokens=700)


TOPICS = {
    "warranty": ("garanti", "warranty", "guarantee", "ضمان", "الضمان", "كفالة"),
    "expiry": ("son kullanma", "skt", "bozul", "expire", "expiry", "best before", "انتهاء", "صلاحية", "الصلاحية"),
    "loan": ("ödünç", "odunc", "emanet", "kimde", "loan", "lent", "borrow", "who has", "إعارة", "اعارة", "معار", "استعار"),
    "low": ("az kal", "bitti", "bitmek", "tükendi", "almam lazım", "alışveriş", "low", "run out", "running out", "shopping",
            "نفد", "ناقص", "قليل", "التسوق"),
}
COUNT_WORDS = ("kaç", "kac", "how many", "how much", "كم")


def ask_offline(question, items, t, today=None, days=filtre.WARN_DAYS):
    """İnternetsiz cevap: konu sözcüklerine (garanti, son kullanma, ödünç, az kalan) ya da aranan eşyaya göre.
    items: list_items() biçiminde bütün eşyalar · t: çeviri işlevi. Satır listesi döndürür."""
    q = norm(question)
    for topic, words in TOPICS.items():
        if any(norm(w) in q for w in words):
            return _topic_answer(topic, items, t, today, days)
    cmd = parse_voice(question)
    terms = [w for w in norm(cmd["query"] or question).split() if len(w) > 1 and w not in {norm(x) for x in COUNT_WORDS}]
    if not terms:
        return [t("Sorunuzu biraz daha açık yazın: „Matkap nerede?“ · „Garantisi biten ne var?“")]
    from .db import term_in
    found = []
    for d in items:
        hay = norm(" ".join((d["name"], d.get("notes", ""), d.get("category_path", ""), d.get("location_path", ""))))
        if all(term_in(x, hay) for x in terms):
            found.append(d)
    if not found:       # en az bir kelime tutanlar
        for d in items:
            hay = norm(d["name"])
            if any(term_in(x, hay) for x in terms):
                found.append(d)
        if not found:
            return [t("„{x}“ bulunamadı.", x=cmd["query"] or question)]
    lines = []
    if any(w in q for w in (norm(x) for x in COUNT_WORDS)):
        lines.append(t("{n} kayıt · toplam {q} adet", n=len(found), q=sum(int(d.get("quantity") or 0) for d in found)))
    for d in found[:8]:
        where = d.get("location_path") or t("yeri belirtilmemiş")
        extra = t(" · ödünç: {x}", x=d["loan_to"]) if d.get("loan_to") else ""
        lines.append(f"• {d['name']} (×{d.get('quantity', 0)}) → 📍 {where}{extra}")
    if len(found) > 8:
        lines.append(t("… ve {n} eşya daha", n=len(found) - 8))
    return lines


def _topic_answer(topic, items, t, today, days):
    lines = []
    if topic in ("warranty", "expiry"):
        field = "warranty_until" if topic == "warranty" else "expires_on"
        rows = [(d, filtre.days_left(d.get(field), today)) for d in items if d.get(field)]
        rows = [(d, n) for d, n in rows if n is not None and n <= days]
        rows.sort(key=lambda x: x[1])
        if not rows:
            return [t("Önümüzdeki {n} gün içinde garantisi biten eşya yok.", n=days) if topic == "warranty"
                    else t("Önümüzdeki {n} gün içinde son kullanma tarihi dolan eşya yok.", n=days)]
        for d, n in rows[:10]:
            when = t("{n} gün önce bitti", n=-n) if n < 0 else t("bugün bitiyor") if n == 0 else t("{n} gün kaldı", n=n)
            lines.append(f"• {d['name']} — {d[field]} ({when}) · 📍 {d.get('location_path') or '—'}")
    elif topic == "loan":
        rows = [d for d in items if d.get("loan_to")]
        if not rows:
            return [t("Ödünç verilmiş eşya yok.")]
        for d in rows[:10]:
            late = filtre.days_left(d.get("loan_due"), today)
            lines.append(f"• {d['name']} → {d['loan_to']}" + (t(" · ⚠ {n} gün gecikti", n=-late) if late is not None and late < 0 else ""))
    else:
        rows = [d for d in items if filtre._is_low(d) or d.get("to_buy") or int(d.get("quantity") or 0) == 0]
        if not rows:
            return [t("Azalan ya da biten eşya yok.")]
        for d in rows[:12]:
            lines.append(f"• {d['name']} — {t('Adet:')} {d.get('quantity', 0)}" +
                         (f" / {t('En az: {n}', n=d['min_qty'])}" if d.get("min_qty") else ""))
    return lines


# ------------------------------------------------------------------ fotoğraftan öneri
def suggest_from_photo(image_bytes, categories, locations, lang, mime="image/jpeg"):
    """Fotoğraftaki eşya için {name, category, location, notes} önerisi (çevrim içi; anahtar gerekir)."""
    p = ("Identify the single main household item / tool / object in this photo for a home inventory app. "
         f"Reply ONLY with JSON: {{\"name\": short item name in {LANG_NAMES.get(lang, 'Türkçe')} (brand/model/size if visible), "
         "\"category\": the best matching category from CATEGORIES (exact text) or \"\", "
         "\"location\": a likely place from PLACES (exact text) or \"\", "
         f"\"notes\": one short line in {LANG_NAMES.get(lang, 'Türkçe')} with visible details (brand, size, colour, model)}}.\n"
         "CATEGORIES: " + json.dumps(categories, ensure_ascii=False) + "\nPLACES: " + json.dumps(locations, ensure_ascii=False))
    out = _json_from(call(p, image=image_bytes, mime=mime, max_tokens=300)) or {}
    return {k: str(out.get(k) or "").strip() for k in ("name", "category", "location", "notes")}


def translate(text, src, dst):
    p = (f"Translate the following home-inventory text from {LANG_NAMES.get(src, src)} to {LANG_NAMES.get(dst, dst)}. "
         "Keep numbers, sizes, brand and model names unchanged. Reply with the translation only.\n\n" + text)
    return call(p, max_tokens=500)
