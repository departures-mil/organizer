"""Organizer — ESKİ KANAL KÖPRÜSÜ (2.1.0.x kurulumları → 2.2.0 kurulumlu sürüm).

Eski kurulumlar yeni sürümü yalnız bu depodaki RSA-3072 imzalı bildirgelerden görür:
  masaüstü (taşınabilir, Python+PySide6):  guncelleme/organizer-masaustu.json  → organizer/ + assets/ zip'i (uygulama içi paket)
  telefon (web paketi + Java kabuğu 1–3):    guncelleme/organizer-telefon.json  (kabuk 4 > kurulu kabuk → APK ister)
                                            guncelleme/organizer-telefon-apk.json → APK (Android kendi "Güncelle" onayını sorar)
Eski karşılaştırma sayıları sırayla karşılaştırır: 2.2.0 > 2.1.0.13 → "yeni sürüm var".

Masaüstü köprü paketi = 2.1.0.13'ün kendi kodu (git: KAYNAK) + "Yeni kurulum gerekli" penceresi (organizer/kopru.py):
latest.json → win-setup kurulum dosyasını indirir (yüzde · MB · kalan · hız), SHA-256 ile doğrular, eski veri klasörünü
%APPDATA%\\Organizer\\eski-veri-konumu.txt'ye yazar (kurulu 2.2.0 ilk açılışta kayıtları, ayarları ve fotoğrafları oradan
KOPYALAR; eski klasör silinmez), programı kapatıp kurulumu başlatır.
Telefon: GitHub Release'teki imzalı APK (aynı Android anahtarı) aynen RSA ile imzalanıp guncelleme/'ye konur.

Kullanım (release YAYINLANDIKTAN SONRA, RSA anahtarının olduğu bilgisayarda — deponun kökünden):
  python araclar/kopru.py --gonder          imzala, guncelleme/ yaz, commit + push
  python araclar/kopru.py                   yalnız imzala ve yaz (gönderme)
  python araclar/kopru.py --kuru            anahtarsız/ağsız: köprü paketini kurup denetler (CI)
Anahtar: ANAHTAR=<guncelleme-imza.pem> ya da sırayla geliştiricinin bilgisayarındaki anahtar klasörü,
  ../anahtarlar/guncelleme-imza.pem. Anahtarın açık kısmı 2.1'deki PUB_N ile aynı olmalı (denetlenir).
"""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "guncelleme")
KAYNAK = "e570b5c"          # 2.1.0.13 (masaüstü + telefon), köprü paketinin tabanı
OWNER, NAME = "departures-mil", "organizer"
KEYS = [os.environ.get("ANAHTAR", ""),
        r"C:\Claude Programlarım\_Anahtarlar\Organizer\guncelleme-imza.pem",
        os.path.join(os.path.expanduser("~"), "Claude Programlarım", "_Anahtarlar", "Organizer", "guncelleme-imza.pem"),
        os.path.join(REPO, "..", "anahtarlar", "guncelleme-imza.pem")]


def surum():
    s = open(os.path.join(REPO, "masaustu", "organizer", "__init__.py"), encoding="utf-8").read()
    return re.search(r'__version__ = "([^"]+)"', s).group(1)


def git_show(path):
    return subprocess.run(["git", "-C", REPO, "show", f"{KAYNAK}:{path}"], check=True, capture_output=True).stdout


def git_files(prefix):
    out = subprocess.run(["git", "-C", REPO, "ls-tree", "-r", "--name-only", KAYNAK, prefix], check=True,
                         capture_output=True, text=True).stdout
    return [x for x in out.splitlines() if x]


# ------------------------------------------------------------------ köprü penceresi (eski programın içine girer)
KOPRU_PY = r'''r"""2.2.0 köprüsü: "Yeni kurulum gerekli" penceresi (yalnız eski taşınabilir 2.1 programında çalışır).
Kurulum dosyasını GitHub Releases latest.json'dan (win-setup) indirir, SHA-256 ile doğrular, eski veri klasörünü
%APPDATA%\Organizer\eski-veri-konumu.txt'ye yazar (yeni program kayıtları oradan kopyalar; eski klasör silinmez),
programı kapatır ve kurulumu başlatır."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout)

from . import i18n

YENI = "@SURUM@"
LATEST = "https://github.com/departures-mil/organizer/releases/latest/download/latest.json"
SAYFA = "https://github.com/departures-mil/organizer/releases/latest"
M = {
    "tr": {"baslik": "Yeni kurulum gerekli",
           "p1": "Organizer {v} yeni bir kurulum programıyla gelir: yeni görünüm, tek tıkla güncelleme (yalnızca değişen kısımlar indirilir) ve daha güvenli eşitleme. Bir kez kurun; sonraki güncellemeler kendiliğinden gelir.",
           "p2": "Kayıtlarınız korunur: eşyalar, ustalar, fotoğraflar, ayarlar ve bulut bağlantısı yeni programa kopyalanır. Bu taşınabilir klasör silinmez.",
           "p3": "„İndir ve kur“ kurulum dosyasını indirir, bu programı kapatır ve kurulumu başlatır; birkaç saniye sonra yeni Organizer açılır. Masaüstüne yeni „Organizer“ kısayolu eklenir.",
           "kur": "İndir ve kur", "sayfa": "Sürümler sayfası", "sonra": "Daha sonra", "iniyor": "Kurulum dosyası indiriliyor",
           "hata": "Kurulum dosyası indirilemedi ({e}). Sürümler sayfasından indirebilirsiniz.", "kalan": "kalan", "dogrula": "Doğrulanıyor…"},
    "en": {"baslik": "New installer required",
           "p1": "Organizer {v} comes with a new installer: a new look, one-click updates (only the changed parts are downloaded) and safer sync. Install it once; later updates arrive automatically.",
           "p2": "Your records are kept: items, craftsmen, photos, settings and the cloud connection are copied to the new program. This portable folder is not deleted.",
           "p3": "\"Download and install\" downloads the installer, closes this program and starts the installation; the new Organizer opens a few seconds later. A new \"Organizer\" desktop shortcut is added.",
           "kur": "Download and install", "sayfa": "Releases page", "sonra": "Later", "iniyor": "Downloading the installer",
           "hata": "The installer could not be downloaded ({e}). You can download it from the releases page.", "kalan": "left", "dogrula": "Verifying…"},
    "ar": {"baslik": "يلزم مثبّت جديد",
           "p1": "يأتي Organizer {v} بمثبّت جديد: مظهر جديد، وتحديث بنقرة واحدة (تُنزَّل الأجزاء المتغيرة فقط)، ومزامنة أكثر أماناً. ثبّته مرة واحدة؛ وستصل التحديثات التالية تلقائياً.",
           "p2": "سجلاتك محفوظة: تُنسخ الأغراض والحرفيون والصور والإعدادات واتصال السحابة إلى البرنامج الجديد. لا يُحذف هذا المجلد المحمول.",
           "p3": "زر «تنزيل وتثبيت» ينزّل ملف التثبيت ويغلق هذا البرنامج ويبدأ التثبيت؛ ثم يُفتح Organizer الجديد بعد ثوانٍ. يُضاف اختصار جديد باسم «Organizer» على سطح المكتب.",
           "kur": "تنزيل وتثبيت", "sayfa": "صفحة الإصدارات", "sonra": "لاحقاً", "iniyor": "جارٍ تنزيل ملف التثبيت",
           "hata": "تعذّر تنزيل ملف التثبيت ({e}). يمكنك تنزيله من صفحة الإصدارات.", "kalan": "متبقٍ", "dogrula": "جارٍ التحقق…"},
}


def T(k, **kw):
    s = M.get(i18n.LANG, M["tr"]).get(k, M["tr"][k])
    return s.format(**kw) if kw else s


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Organizer-kopru"})
    return urllib.request.urlopen(req, timeout=timeout)


def _mb(b):
    s = f"{b / 1048576:.1f}"
    return s.replace(".", ",") if i18n.LANG == "tr" else s


class _Is(QObject):
    ilerleme = Signal(str, int)
    bitti = Signal(str)
    hata = Signal(str)


def _isaret():
    """Kurulu sürüm kayıtları buradan kopyalasın: eski (taşınabilir) veri klasörü."""
    from .paths import data_dir
    eski = os.path.abspath(str(data_dir()))
    yeni = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Organizer")
    if os.path.normcase(eski) == os.path.normcase(os.path.abspath(yeni)):
        return
    os.makedirs(yeni, exist_ok=True)
    with open(os.path.join(yeni, "eski-veri-konumu.txt"), "w", encoding="utf-8") as f:
        f.write(eski)


def _indir(sinyal):
    try:
        with _get(LATEST) as r:
            man = json.loads(r.read().decode("utf-8"))
        a = (man.get("assets") or {}).get("win-setup") or {}
        if not a.get("file") or not a.get("sha256"):
            raise RuntimeError("win-setup")
        url = f"https://github.com/departures-mil/organizer/releases/download/v{man['version']}/{a['file']}"
        hedef = os.path.join(tempfile.gettempdir(), a["file"])
        top = int(a.get("size") or 0)
        h = hashlib.sha256()
        t0, n = time.monotonic(), 0
        with _get(url, timeout=60) as r, open(hedef + ".part", "wb") as f:
            while True:
                b = r.read(262144)
                if not b:
                    break
                f.write(b)
                h.update(b)
                n += len(b)
                hiz = n / max(0.001, time.monotonic() - t0)
                p = int(n * 100 / top) if top else 0
                sinyal.ilerleme.emit(f"%{p} · {_mb(n)} / {_mb(top)} MB · {T('kalan')} {_mb(max(top - n, 0))} MB · {_mb(hiz)} MB/s", p)
        sinyal.ilerleme.emit(T("dogrula"), 100)
        if h.hexdigest() != a["sha256"].lower():
            os.remove(hedef + ".part")
            raise RuntimeError("SHA-256")
        os.replace(hedef + ".part", hedef)
        sinyal.bitti.emit(hedef)
    except Exception as e:  # noqa: BLE001
        sinyal.hata.emit(str(e) or type(e).__name__)


class KopruPenceresi(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(T("baslik"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        b = QLabel(T("baslik"))
        b.setObjectName("SectionTitle")
        v.addWidget(b)
        for k in ("p1", "p2", "p3"):
            l = QLabel(T(k, v=YENI))
            l.setWordWrap(True)
            v.addWidget(l)
        self.durum = QLabel("")
        self.durum.setWordWrap(True)
        self.cubuk = QProgressBar()
        self.cubuk.setRange(0, 100)
        self.cubuk.setTextVisible(False)
        self.cubuk.hide()
        v.addWidget(self.durum)
        v.addWidget(self.cubuk)
        r = QHBoxLayout()
        self.sayfa = QPushButton(T("sayfa"))
        self.sayfa.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SAYFA)))
        self.sonra = QPushButton(T("sonra"))
        self.sonra.clicked.connect(self.reject)
        self.kur = QPushButton(T("kur"))
        self.kur.setObjectName("Primary")
        self.kur.clicked.connect(self._kur)
        r.addWidget(self.sayfa)
        r.addStretch(1)
        r.addWidget(self.sonra)
        r.addWidget(self.kur)
        v.addLayout(r)
        self.s = _Is()
        self.s.ilerleme.connect(self._ilerleme)
        self.s.bitti.connect(self._bitti)
        self.s.hata.connect(self._hata)

    def _kur(self):
        self.kur.setEnabled(False)
        self.sonra.setEnabled(False)
        self.cubuk.show()
        self.durum.setText(T("iniyor") + "…")
        threading.Thread(target=_indir, args=(self.s,), daemon=True).start()

    def _ilerleme(self, metin, p):
        self.durum.setText(T("iniyor") + "\n" + metin)
        self.cubuk.setValue(p)

    def _hata(self, e):
        self.durum.setText("⚠ " + T("hata", e=e))
        self.kur.setEnabled(True)
        self.sonra.setEnabled(True)

    def _bitti(self, yol):
        try:
            _isaret()
        except OSError:
            pass
        self.accept()
        try:
            self.win.close()          # son eşitleme (bulut) yapılır
        except Exception:
            pass
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([yol], creationflags=flags, close_fds=True)
        QTimer.singleShot(400, QApplication.quit)


_acik = None


def goster(win):
    global _acik
    if _acik is not None and _acik.isVisible():
        _acik.raise_()
        return
    _acik = KopruPenceresi(win)
    _acik.show()
'''


def build_desktop_bridge(ver):
    """2.1.0.13 kodu + köprü penceresi → eski güncelleyicinin kuracağı zip (organizer/ ve assets/)."""
    files = {}
    for p in git_files("masaustu/organizer") + git_files("masaustu/assets"):
        files[p[len("masaustu/"):]] = git_show(p)
    init = files["organizer/__init__.py"].decode("utf-8")
    init, n = re.subn(r'__version__ = "[^"]+"', f'__version__ = "{ver}"', init)
    assert n == 1
    files["organizer/__init__.py"] = init.encode("utf-8")
    files["organizer/kopru.py"] = KOPRU_PY.replace("@SURUM@", ver).encode("utf-8")
    app = files["organizer/app.py"].decode("utf-8")
    a = "    QTimer.singleShot(4000, ctl.check_update_once)  # güncellemeler GitHub'dan: bulut hesabı beklenmez\n"
    assert a in app, "app.py: beklenen satır yok"
    app = app.replace(a, "    QTimer.singleShot(2500, lambda: __import__('organizer.kopru', fromlist=['goster']).goster(ctl.win))"
                         "  # 2.2.0 köprüsü: yeni kurulum gerekli\n")
    files["organizer/app.py"] = app.encode("utf-8")
    mw = files["organizer/main_window.py"].decode("utf-8")
    a = "    def _update_clicked(self):\n        u = self.updater\n"
    assert a in mw, "main_window.py: beklenen satır yok"
    mw = mw.replace(a, "    def _update_clicked(self):\n        from . import kopru\n        return kopru.goster(self)\n        u = self.updater\n")
    files["organizer/main_window.py"] = mw.encode("utf-8")
    for name, data in files.items():          # sözdizimi denetimi
        if name.endswith(".py"):
            compile(data.decode("utf-8"), name, "exec")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            zi = zipfile.ZipInfo(name, (2026, 11, 24, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, files[name])
    return buf.getvalue()


def old_pub_n():
    src = git_show("masaustu/organizer/updater.py").decode("utf-8")
    m = re.search(r"PUB_N = int\(\s*((?:\"[0-9a-f]+\"\s*)+),\s*16\)", src)
    return int("".join(re.findall(r'"([0-9a-f]+)"', m.group(1))), 16)


def load_key():
    from cryptography.hazmat.primitives import serialization
    for k in KEYS:
        if k and os.path.isfile(k):
            key = serialization.load_pem_private_key(open(k, "rb").read(), password=None)
            if key.public_key().public_numbers().n != old_pub_n():
                sys.exit(f"HATA: {k} eski programların tanıdığı anahtar değil (PUB_N tutmuyor).")
            return key
    sys.exit("HATA: RSA anahtarı bulunamadı (ANAHTAR=<guncelleme-imza.pem> verin).")


def sign(key, blob):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    return base64.b64encode(key.sign(blob, padding.PKCS1v15(), hashes.SHA256())).decode()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Organizer-kopru"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def manifest(ver, notes, blob, sig, dosya, **extra):
    return dict({"surum": ver, "notlar": notes, "boyut": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "imza": sig,
                 "yayin": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "dosya": dosya}, **extra)


def main():
    args = sys.argv[1:]
    ver = surum()
    zipb = build_desktop_bridge(ver)
    with zipfile.ZipFile(io.BytesIO(zipb)) as z:
        names = z.namelist()
        assert "organizer/kopru.py" in names and any(n.startswith("assets/") for n in names)
        assert f'__version__ = "{ver}"' in z.read("organizer/__init__.py").decode()
    print(f"masaüstü köprü paketi: {len(zipb)} bayt, {len(names)} dosya, sürüm {ver}")
    if "--kuru" in args:
        print("kuru çalıştırma: TAMAM (imzalanmadı, yazılmadı)")
        return
    key = load_key()
    man = json.loads(fetch(f"https://github.com/{OWNER}/{NAME}/releases/latest/download/latest.json"))
    if man.get("version") != ver:
        sys.exit(f"HATA: GitHub'daki son sürüm {man.get('version')}, beklenen {ver}. Önce release yayınlanmalı.")
    notes_tr = (man.get("notes") or {}).get("tr") or f"Organizer {ver}"
    note = f"{ver}: yeni kurulum gerekli — " + notes_tr.split("\n")[0]
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                      # eski paketler (artık bildirgede yok)
        if f.endswith((".zip", ".apk")):
            os.remove(os.path.join(OUT, f))
    # masaüstü
    zname = f"organizer-masaustu-{ver}.zip"
    open(os.path.join(OUT, zname), "wb").write(zipb)
    json.dump(manifest(ver, note, zipb, sign(key, zipb), zname, sistem=1),
              open(os.path.join(OUT, "organizer-masaustu.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # telefon (APK)
    a = (man.get("assets") or {}).get("android")
    if a:
        apk = fetch(f"https://github.com/{OWNER}/{NAME}/releases/download/v{ver}/{a['file']}")
        if hashlib.sha256(apk).hexdigest() != a["sha256"]:
            sys.exit("HATA: APK SHA-256 tutmuyor")
        aname = f"organizer-telefon-apk-{ver}.apk"
        open(os.path.join(OUT, aname), "wb").write(apk)
        asig = sign(key, apk)
        json.dump(manifest(ver, note, apk, asig, aname, kabuk=4),
                  open(os.path.join(OUT, "organizer-telefon-apk.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # web bildirgesi: kabuk 4 > kurulu kabuk (1–3) → eski telefon APK yolunu seçer
        json.dump(manifest(ver, note, apk, asig, aname, kabuk=4),
                  open(os.path.join(OUT, "organizer-telefon.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"telefon köprüsü: {aname} ({len(apk)} bayt)")
    else:
        print("UYARI: release'te android kanalı yok — telefon köprüsü yazılmadı")
    print("guncelleme/ yazıldı.")
    if "--gonder" in args:
        g = ["git", "-C", REPO]
        subprocess.run(g + ["add", "-A", "guncelleme"], check=True)
        subprocess.run(g + ["commit", "-m", f"Eski kanal köprüsü: 2.1.0.x → {ver} (imzalı)"], check=True)
        subprocess.run(g + ["push", "origin", "HEAD:main"], check=True)
        print("gönderildi.")


if __name__ == "__main__":
    main()
