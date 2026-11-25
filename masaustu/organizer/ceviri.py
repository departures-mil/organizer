"""2.3.0 — Eşya adı ve notların Türkçe · İngilizce · Arapça çevirisi.
Önce çevrim içi (kendi yapay zeka anahtarınız varsa yapay zeka, yoksa ücretsiz MyMemory çeviri servisi),
internet yoksa çevrim dışı sözlük (organizer/sozluk.py) ile kelime kelime."""
import json
import re
import urllib.parse
import urllib.request

from .db import norm
from .sozluk import LANG_INDEX, WORDS

WEB_API = "https://api.mymemory.translated.net/get"
_SUFFIXES = sorted(["ındaki", "indeki", "undaki", "ündeki", "ndaki", "ndeki", "daki", "deki", "taki", "teki", "ları", "leri", "lar", "ler", "ları", "ndan", "nden", "dan", "den", "tan", "ten", "nda", "nde", "da", "de",
                    "ta", "te", "nın", "nin", "nun", "nün", "ın", "in", "un", "ün", "sı", "si", "su", "sü", "yı", "yi", "yu",
                    "yü", "ı", "i", "u", "ü", "ya", "ye", "a", "e"], key=len, reverse=True)
_index = {}


def _idx(lang):
    if lang not in _index:
        i = LANG_INDEX[lang]
        _index[lang] = {norm(w[i]): w for w in WORDS}
    return _index[lang]


def detect(text):
    s = str(text or "")
    if re.search(r"[؀-ۿ]", s):
        return "ar"
    if re.search(r"[çğışöüÇĞİŞÖÜ]", s):
        return "tr"
    words = norm(s).split()
    tr = sum(1 for w in words if w in _idx("tr") or _stem(w, "tr") in _idx("tr"))
    en = sum(1 for w in words if w in _idx("en"))
    return "en" if en > tr else "tr"


def _stem(w, lang):
    if lang == "ar":
        return w[2:] if w.startswith("ال") and len(w) > 3 else w
    if lang != "tr":
        return w[:-1] if w.endswith("s") and len(w) > 3 else w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3 and w[:-len(suf)] in _idx("tr"):
            return w[:-len(suf)]
    return w


def offline(text, src, dst):
    """Sözlükle çeviri. (çeviri, bilinen kelime oranı 0..1) döndürür; bilinmeyen kelimeler olduğu gibi kalır."""
    if src == dst or not str(text or "").strip():
        return text, 1.0
    idx, j = _idx(src), LANG_INDEX[dst]
    out_lines, known, total = [], 0, 0
    for line in str(text).split("\n"):
        tokens = re.findall(r"\w+(?:[-']\w+)*|[^\w\s]+|\s+", line)
        words = [(k, tok) for k, tok in enumerate(tokens) if re.match(r"\w", tok)]
        res = list(tokens)
        k = 0
        while k < len(words):
            matched = False
            for n in (4, 3, 2, 1):           # en uzun kalıp önce ("şarjlı matkap" > "matkap")
                if k + n > len(words):
                    continue
                seg = [norm(w[1]) for w in words[k:k + n]]
                keys = [" ".join(seg)]
                keys.append(" ".join(seg[:-1] + [_stem(seg[-1], src)]))
                hit = next((idx[x] for x in keys if x in idx), None)
                if hit:
                    first, last = words[k][0], words[k + n - 1][0]
                    res[first] = hit[j]
                    for z in range(first + 1, last + 1):
                        res[z] = ""
                    known += n
                    k += n
                    matched = True
                    break
            if not matched:
                if words[k][1].isdigit():
                    known += 1
                k += 1
        total += len(words)
        out_lines.append(re.sub(r"\s{2,}", " ", "".join(res)).strip())
    return "\n".join(out_lines), (known / total if total else 1.0)


def web(text, src, dst):
    q = urllib.parse.urlencode({"q": text[:480], "langpair": f"{src}|{dst}"})
    with urllib.request.urlopen(f"{WEB_API}?{q}", timeout=12) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not out or "MYMEMORY WARNING" in out.upper() or str(data.get("responseStatus")) not in ("200", "None"):
        raise OSError(out or "web")
    return out


def translate(text, dst, src=None, allow_online=True):
    """→ (çeviri, yol) · yol: 'ai' (yapay zeka) · 'web' (çeviri servisi) · 'offline' (sözlük)."""
    text = str(text or "").strip()
    src = src or detect(text)
    if not text or src == dst:
        return text, "offline"
    if allow_online:
        from . import zeka
        if zeka.cfg():
            try:
                return zeka.translate(text, src, dst), "ai"
            except zeka.AiError:
                pass
        try:
            return web(text, src, dst), "web"
        except Exception:
            pass
    return offline(text, src, dst)[0], "offline"
