"""Meslek simgeleri: her usta/dükkan için mesleğine uygun küçük bir simge.

1) Bilinen meslekler (Türkçe, İngilizce, Arapça) programla gelen simgelerle eşleşir (assets/meslek_simgeleri.json).
2) Eşleşmeyen yeni bir meslek yazılınca simge internetten kendiliğinden bulunur: meslek adı İngilizceye
   çevrilir (MyMemory), Iconify simge kütüphanesinde aranır, bulunan simge veri klasörüne kaydedilir.
3) İnternet yoksa ya da bir şey bulunamazsa usta için baretli adam, dükkan için dükkan simgesi gösterilir.
"""
import json
import os
import re
import urllib.parse
import urllib.request

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from .db import norm
from .paths import asset

ICON_COLOR = "#1d5f74"
BADGE_COLOR = "#e6f3f1"
ICON_API = os.environ.get("ORGANIZER_ICON_API", "https://api.iconify.design")
TRANSLATE_API = os.environ.get("ORGANIZER_TRANSLATE_API", "https://api.mymemory.translated.net")
ICON_SETS = "mdi,tabler,material-symbols,ph,fluent,healthicons,game-icons"

_DATA = None


def _data():
    global _DATA
    if _DATA is None:
        with open(asset("meslek_simgeleri.json"), encoding="utf-8") as f:
            _DATA = json.load(f)
        _DATA["_rules"] = [([norm(p) for p in parts], key) for parts, key in _DATA["rules"]]
    return _DATA


def slug(text):
    s = re.sub(r"\s+", "-", norm(text).strip())
    s = re.sub(r"[^\w-]", "", s)
    return s[:60] or "x"


def bundled_key(text):
    """Bilinen bir meslekse programla gelen simgenin adı, değilse None."""
    hay = " " + norm(text) + " "
    if not hay.strip():
        return None
    for parts, key in _data()["_rules"]:
        if any(p and p in hay for p in parts):
            return key
    return None


def bundled_svg(key, color=ICON_COLOR):
    body = _data()["icons"][key].replace("currentColor", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">{body}</svg>'


def default_key(kind):
    return _data()["default_dukkan" if kind == "dukkan" else "default_usta"]


# ------------------------------------------------------------------ internetten bulma
def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Organizer/1.0.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def translate_to_english(text):
    lang = "ar" if re.search(r"[؀-ۿ]", text) else "tr"
    q = urllib.parse.urlencode({"q": text, "langpair": f"{lang}|en"})
    try:
        data = json.loads(_get(f"{TRANSLATE_API}/get?{q}"))
        out = (data.get("responseData") or {}).get("translatedText") or ""
    except Exception:
        return ""
    out = re.sub(r"[^A-Za-z\s-]", " ", out).strip().lower()
    return out if out and out != text.lower() else ""


def search_icon(query):
    q = urllib.parse.urlencode({"query": query, "limit": 32, "prefixes": ICON_SETS})
    data = json.loads(_get(f"{ICON_API}/search?{q}"))
    for full in data.get("icons") or []:
        if ":" in full:
            return full
    return None


def lookup_online(text):
    """Meslek için internetten bir SVG simge bulur; bulamazsa None."""
    queries = []
    en = translate_to_english(text)
    if en:
        queries += [en, en.split()[-1], en.split()[0]]
    if re.fullmatch(r"[A-Za-z\s-]+", text.strip()):
        queries.insert(0, text.strip().lower())
    seen = set()
    for q in queries:
        if not q or q in seen or len(q) < 3:
            continue
        seen.add(q)
        # İngilizce karşılık bilinen bir meslekse programla gelen simgeyi kullan
        key = bundled_key(q)
        if key:
            return bundled_svg(key)
        try:
            full = search_icon(q)
        except Exception:
            return None
        if full:
            prefix, name = full.split(":", 1)
            color = urllib.parse.quote(ICON_COLOR)
            svg = _get(f"{ICON_API}/{prefix}/{name}.svg?color={color}&height=48").decode("utf-8")
            if "<svg" in svg:
                return svg
    return None


class _Fetch(QThread):
    found = Signal(str, str)   # slug, svg

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            svg = lookup_online(self.text)
        except Exception:
            svg = None
        self.found.emit(slug(self.text), svg or "")


class ProfessionIcons(QObject):
    """Simgeleri bellekte ve veri klasöründe saklar; eksikleri arka planda indirir."""
    changed = Signal()

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.dir = data_dir / "meslek_simgeleri"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._pix = {}
        self._tried = set()
        self._workers = []

    def svg(self, text, kind="usta"):
        key = bundled_key(text or "")
        if key:
            return bundled_svg(key)
        if text and text.strip():
            f = self.dir / (slug(text) + ".svg")
            if f.exists():
                return f.read_text(encoding="utf-8")
            self.fetch(text)
        return bundled_svg(default_key(kind))

    def fetch(self, text):
        s = slug(text)
        if s in self._tried or bundled_key(text):
            return
        self._tried.add(s)
        w = _Fetch(text)
        w.found.connect(self._found)
        w.finished.connect(lambda w=w: self._workers.remove(w))
        self._workers.append(w)
        w.start()

    def _found(self, s, svg):
        if not svg:
            return
        (self.dir / (s + ".svg")).write_text(svg, encoding="utf-8")
        self._pix.clear()
        self.changed.emit()

    def pixmap(self, text, kind="usta", size=40):
        k = (text, kind, size)
        if k not in self._pix:
            self._pix[k] = badge(self.svg(text, kind), size)
        return self._pix[k]

    def icon(self, text, kind="usta", size=40):
        return QIcon(self.pixmap(text, kind, size))

    def wait(self, ms=30000):
        for w in list(self._workers):
            w.wait(ms)


def badge(svg, size):
    """Açık renkli daire içinde simge."""
    from PySide6.QtSvg import QSvgRenderer
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(BADGE_COLOR))
    p.drawEllipse(0, 0, size, size)
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if r.isValid():
        m = size * 0.2
        box = QRectF(m, m, size - 2 * m, size - 2 * m)
        vb = r.viewBoxF()
        if vb.width() > 0 and vb.height() > 0:   # oranı koru
            scale = min(box.width() / vb.width(), box.height() / vb.height())
            w, h = vb.width() * scale, vb.height() * scale
            box = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
        r.render(p, box)
    p.end()
    return pix
