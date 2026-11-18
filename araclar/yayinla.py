"""Organizer — güncelleme yayınlama aracı (masaüstü + telefon).

1.4.0'dan itibaren güncellemeler bu GitHub deposunun "guncelleme/" klasöründen dağıtılır; programlar
https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme/<tür>.json dosyasını okur.
İstenirse aynı paket eski yola (Firebase "guncelleme" koleksiyonu) da yazılır (--firebase); 1.4.0 öncesi
kurulumlar yalnızca orayı okur.

Kullanım (deponun kökünden):
  python3 araclar/yayinla.py masaustu  masaustu  "notlar" [--firebase]
  python3 araclar/yayinla.py telefon   telefon   "notlar" [--kabuk 1] [--firebase]
  python3 araclar/yayinla.py telefon-apk Organizer.apk "notlar" --surum 1.5.0 --kabuk 2 [--firebase]
  python3 araclar/yayinla.py durum           (GitHub klasöründeki ve Firebase'deki bildirgeleri gösterir)
Sonra: git add guncelleme && git commit && git push  → programlar yeni sürümü görür.

Ortam:
  ANAHTAR    = guncelleme-imza.pem yolu (GİZLİ — depoya ASLA eklenmez; varsayılan ../anahtarlar/guncelleme-imza.pem)
  VERITABANI = organizer.db yolu (yalnızca --firebase için: Firebase ayarı ve oturumu buradan okunur)

Paket düzeni:
  masaustu : zip içinde organizer/ ve assets/ ; sürüm organizer/__init__.py içinden okunur
  telefon  : zip içinde web dosyaları (index.html, app.js, ...) ; sürüm app.js APP_VERSION'dan okunur
  imza     : RSA-3072 PKCS#1 v1.5 + SHA-256, ham zip/apk baytları üzerinde, base64
  GitHub   : guncelleme/<tür>.json = {surum, notlar, boyut, sha256, imza, yayin, dosya, sistem|kabuk}
             guncelleme/<tür>-<sürüm>.zip (apk için .apk)
  Firebase : guncelleme/<tür> = bildirge, guncelleme/<tür>-<sürüm>-<i> = {veri: bytes} (≤ 700 KB parça)
"""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "guncelleme")
KEY = os.environ.get("ANAHTAR", os.path.join(REPO, "..", "anahtarlar", "guncelleme-imza.pem"))
DB = os.environ.get("VERITABANI", os.path.join(REPO, "..", "yedek", "organizer.db"))
PART = 700_000
KINDS = ("organizer-masaustu", "organizer-telefon", "organizer-telefon-apk")
ALIAS = {"masaustu": "organizer-masaustu", "telefon": "organizer-telefon", "telefon-apk": "organizer-telefon-apk"}


# ------------------------------------------------------------------ firebase (eski yol)
def _settings():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    s = dict(c.execute("select key, value from settings"))
    c.close()
    cfg = s["fb_config"]
    api = re.search(r"""apiKey["']?\s*:\s*["']([^"']+)""", cfg).group(1)
    proj = re.search(r"""projectId["']?\s*:\s*["']([^"']+)""", cfg).group(1)
    return api, proj, s["fb_refresh"]


def _req(method, url, body=None, form=False, tok=None):
    h, data = {}, None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
    if tok:
        h["Authorization"] = "Bearer " + tok
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=120) as x:
            raw = x.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Firebase hatası {e.code}: {e.read()[:400]!r}")


class FB:
    def __init__(self):
        self.api, self.proj, refresh = _settings()
        r = _req("POST", f"https://securetoken.googleapis.com/v1/token?key={self.api}",
                 {"grant_type": "refresh_token", "refresh_token": refresh}, form=True)
        self.tok = r["id_token"]
        self.root = f"projects/{self.proj}/databases/(default)/documents"
        self.base = f"https://firestore.googleapis.com/v1/{self.root}"

    @staticmethod
    def val(v):
        if isinstance(v, bool):
            return {"booleanValue": v}
        if isinstance(v, int):
            return {"integerValue": str(v)}
        if isinstance(v, bytes):
            return {"bytesValue": base64.b64encode(v).decode()}
        return {"stringValue": str(v)}

    def write(self, path, fields):
        return {"update": {"name": f"{self.root}/{path}", "fields": {k: self.val(v) for k, v in fields.items()}}}

    def commit(self, writes):
        _req("POST", f"https://firestore.googleapis.com/v1/{self.root}:commit", {"writes": writes}, tok=self.tok)

    def get(self, path):
        try:
            d = _req("GET", f"{self.base}/{path}", tok=self.tok)
        except SystemExit as e:
            if "404" in str(e):
                return None
            raise
        out = {}
        for k, v in d.get("fields", {}).items():
            t, x = next(iter(v.items()))
            out[k] = int(x) if t == "integerValue" else x
        return out


# ------------------------------------------------------------------ paketleme
def sign(blob):
    key = serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)
    return base64.b64encode(key.sign(blob, padding.PKCS1v15(), hashes.SHA256())).decode()


def _zip_dir(root, prefixes=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dns, fns in os.walk(root):
            dns[:] = sorted(d for d in dns if d != "__pycache__")
            for fn in sorted(fns):
                if fn.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if prefixes and not rel.startswith(prefixes):
                    continue
                zi = zipfile.ZipInfo(rel, (2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, open(full, "rb").read())
    return buf.getvalue()


def version_of(kind, src):
    if kind == "organizer-masaustu":
        txt = open(os.path.join(src, "organizer", "__init__.py"), encoding="utf-8").read()
        return re.search(r'__version__\s*=\s*"([^"]+)"', txt).group(1)
    if kind == "organizer-telefon":
        txt = open(os.path.join(src, "app.js"), encoding="utf-8").read()
        return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', txt).group(1)
    raise SystemExit("--surum gerekli")


def build(kind, src):
    if kind == "organizer-masaustu":
        return _zip_dir(src, ("organizer/", "assets/"))
    if kind == "organizer-telefon":
        return _zip_dir(src)
    return open(src, "rb").read()


def to_github(kind, ver, blob, man):
    os.makedirs(OUT, exist_ok=True)
    ext = "apk" if kind.endswith("-apk") else "zip"
    name = f"{kind}-{ver}.{ext}"
    for old in os.listdir(OUT):   # depo şişmesin: aynı türün eski paketleri silinir
        if re.fullmatch(re.escape(kind) + r"-\d+(\.\d+)*\.(zip|apk)", old) and old != name:
            os.remove(os.path.join(OUT, old))
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(blob)
    gman = dict(man, dosya=name)
    with open(os.path.join(OUT, f"{kind}.json"), "w", encoding="utf-8") as f:
        json.dump(gman, f, ensure_ascii=False, indent=1)
    print(f"GitHub klasörü: guncelleme/{name} + guncelleme/{kind}.json")


def to_firebase(kind, ver, blob, man):
    fb = FB()
    parts = [blob[i:i + PART] for i in range(0, len(blob), PART)]
    for i, p in enumerate(parts):    # önce parçalar, en son bildirge (yarım paket görünmesin)
        fb.commit([fb.write(f"guncelleme/{kind}-{ver}-{i}", {"veri": p})])
    fb.commit([fb.write(f"guncelleme/{kind}", dict(man, parca=len(parts)))])
    print(f"Firebase: guncelleme/{kind} ({len(parts)} parça)")


def publish(kind, src, notes, surum=None, extra=None, firebase=False):
    ver = surum or version_of(kind, src)
    if not re.fullmatch(r"\d+(\.\d+)*", ver):
        raise SystemExit(f"Geçersiz sürüm: {ver}")
    blob = build(kind, src)
    man = {"surum": ver, "notlar": notes, "boyut": len(blob),
           "sha256": hashlib.sha256(blob).hexdigest(), "imza": sign(blob),
           "yayin": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    man.update(extra or {})
    to_github(kind, ver, blob, man)
    if firebase:
        to_firebase(kind, ver, blob, man)
    print(f"{kind} {ver} hazır: {len(blob)} bayt")
    return man


def status(firebase=False):
    for k in KINDS:
        p = os.path.join(OUT, f"{k}.json")
        m = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        m.pop("imza", None)
        print("GitHub  ", k, json.dumps(m, ensure_ascii=False))
    if firebase:
        fb = FB()
        for k in KINDS:
            m = fb.get(f"guncelleme/{k}") or {}
            m.pop("imza", None)
            print("Firebase", k, json.dumps(m, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    fbase = "--firebase" in a
    a = [x for x in a if x != "--firebase"]
    if not a or a[0] == "durum":
        status(fbase)
        sys.exit()
    kind = ALIAS.get(a[0], a[0])
    if kind not in KINDS:
        raise SystemExit("tür: masaustu | telefon | telefon-apk | durum")
    src, notes = a[1], (a[2] if len(a) > 2 else "")
    opt = dict(zip(a[3::2], a[4::2]))
    extra = {}
    if kind == "organizer-masaustu":
        extra["sistem"] = int(opt.get("--sistem", 1))
    else:
        extra["kabuk"] = int(opt.get("--kabuk", 1))
    publish(kind, src, notes, opt.get("--surum"), extra, fbase)
