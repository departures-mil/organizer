"""Uygulama içinden güncelleme (masaüstü).

1.4.0'dan itibaren güncellemeler GitHub'dan gelir (herkese açık depo, bulut hesabı gerekmez):
  https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme/organizer-masaustu.json
      → {surum, notlar, sistem, boyut, sha256, imza, dosya}
  .../guncelleme/<dosya>  → imzalı zip
GitHub'a ulaşılamazsa eski yol denenir: kullanıcının Firebase'indeki "guncelleme" koleksiyonu:
  guncelleme/organizer-masaustu            → {surum, notlar, sistem, boyut, parca, sha256, imza}
  guncelleme/organizer-masaustu-<surum>-<i> → {veri: zip parçası}
Zip, programın "organizer" ve "assets" klasörlerini içerir ve geliştiricinin anahtarıyla imzalıdır;
imzası tutmayan paket kurulmaz. Kurulan sürüm veri klasöründe guncelleme/organizer-masaustu-<surum> altına açılır ve
guncelleme/etkin.txt dosyasına yazılır; main.py açılışta onu yükler. Yeni sürüm açılamazsa main.py
kendiliğinden programla gelen sürüme döner.
"""
import base64
import hashlib
import time
import hmac
import io
import json
import os
import urllib.error
import urllib.request
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import __version__, goster
from .sync import FirebaseClient, SyncError

KIND = "organizer-masaustu"
GITHUB_RAW = "https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme"
# Bu kurulumun (Python, PySide6, başlatıcı, main.py) düzeyi. Bir güncelleme daha yükseğini isterse
# uygulama içinden kurulamaz; tam paket gerekir.
SISTEM = 1

# Güncelleme imzası: RSA-3072, PKCS#1 v1.5, SHA-256 (özel anahtar yalnızca geliştiricide)
PUB_N = int(
    "d552d270eb0f59ac384d346d2ed9262911853e1387f6e1a56bc8defc19bb60e50cc3401587503c5807630fe2c791aee7"
    "822da01c0e2197b7b94113a8896423cb8335a75698d6703197ba43256e0da3dd701f48dea4f259e8732fa448df3fbef2"
    "5048d19aa444088b601afa16b5310ca2e93285629965690155087c5f7e4bd60545495d5635c7a30f24af7e9c15412128"
    "a1a9380cb5397555eab88b7bf20d6091b105a977ccc02204e20fd7e0749509ecb2e3aa61cfdb261e9e3a9823043078a9"
    "203c56deb95fa9c523823795057da3f7bc839e11040863df4aa681410f24111fc3cc8cb0ae3e3c1d402bf3a9168c786b"
    "0c3ac9709faf7312e8bb5c4428a671e9872d2b45f6eb6d00b2d06460924c6dc3fe5a25f29e795792a224ce6ef55e86ab"
    "c6b2015d82fc757100becce6feed3ba894b6a933561c99a61a6e8ad7bd49d41816dfe63debe979cbca77509087179cf9"
    "80d1ebbf25637245f80f2c25f4905e1062744409aa9f58ebf95826e26440f2f11c5f91660ade899a75166e8b7093690b"
    , 16)   # 2.1.0.11: yeni anahtar (eskisi kayboldu)
PUB_E = 65537
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def verify(data: bytes, sig: bytes) -> bool:
    k = (PUB_N.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= PUB_N:
        return False
    em = pow(s, PUB_E, PUB_N).to_bytes(k, "big")
    di = _SHA256_PREFIX + hashlib.sha256(data).digest()
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(di)) + b"\x00" + di
    return hmac.compare_digest(em, expected)


def ota_root(data_dir) -> Path:
    return Path(data_dir) / "guncelleme"


def skipped(data_dir):
    try:
        return set((ota_root(data_dir) / "bozuk.txt").read_text(encoding="utf-8").split())
    except OSError:
        return set()


def active_version(data_dir):
    try:
        return (ota_root(data_dir) / "etkin.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ GitHub
def _http(url, timeout=30):
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}t={int(time.time())}",   # önbellekteki eski bildirge gelmesin
                                 headers={"User-Agent": f"Organizer/{__version__}", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


def github_manifest():
    with _http(f"{GITHUB_RAW}/{KIND}.json") as r:
        man = json.loads(r.read().decode("utf-8"))
    man["_kaynak"] = "github"
    return man


def github_download(man, progress=None):
    name = man.get("dosya") or ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise UpdateError("Güncelleme bildirgesi bozuk.")
    total = int(man.get("boyut") or 0)
    buf = bytearray()
    if progress:
        progress(0, total)
    with _http(f"{GITHUB_RAW}/{name}", timeout=60) as r:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            buf += chunk
            if progress:
                progress(len(buf), max(total, len(buf)))
    return bytes(buf)


def _usable(man, data_dir):
    return bool(man and man.get("surum")) and vkey(man["surum"]) > vkey(__version__) \
        and man["surum"] not in skipped(data_dir)


# ------------------------------------------------------------------ denetle / indir / kur
def check(client, data_dir):
    """Yeni sürüm varsa bildirgesini (dict) döndürür, yoksa None. Önce GitHub, ulaşılamazsa Firebase."""
    gh_error = None
    try:
        man = github_manifest()
        return man if _usable(man, data_dir) else None
    except (urllib.error.URLError, OSError, ValueError) as e:
        gh_error = e
    client = client() if callable(client) else client
    if client is None:
        from .i18n import t
        raise UpdateError(t("Güncelleme sunucusuna ulaşılamadı. İnternet bağlantısını denetleyin."))
    man = client.get_doc(f"guncelleme/{KIND}")
    if man:
        man["_kaynak"] = "firebase"
    return man if _usable(man, data_dir) else None


def download(client, man, progress=None):
    if man.get("_kaynak") == "github":
        blob = github_download(man, progress)
        return _verified(man, blob)
    client = client() if callable(client) else client
    if client is None:
        raise UpdateError("Güncelleme paketi indirilemedi.")
    parts = []
    n = int(man.get("parca") or 0)
    total = int(man.get("boyut") or 0)
    done = 0
    if progress:
        progress(0, total)
    for i in range(n):
        doc = client.get_doc(f"guncelleme/{KIND}-{man['surum']}-{i}")
        if not doc or not isinstance(doc.get("veri"), (bytes, bytearray)):
            raise UpdateError("Güncelleme paketi eksik. Biraz sonra yeniden deneyin.")
        parts.append(bytes(doc["veri"]))
        done += len(parts[-1])
        if progress:
            progress(done, max(total, done))
    return _verified(man, b"".join(parts))


def _verified(man, blob):
    if len(blob) != int(man.get("boyut") or -1) or hashlib.sha256(blob).hexdigest() != man.get("sha256"):
        raise UpdateError("Güncelleme paketi bozuk indi. Yeniden deneyin.")
    try:
        sig = base64.b64decode(man.get("imza") or "")
    except ValueError:
        sig = b""
    if not verify(blob, sig):
        raise UpdateError("Güncelleme paketinin imzası doğrulanamadı; kurulmadı.")
    return blob


def install(data_dir, man, blob):
    """İmzası doğrulanmış paketi açar ve bir sonraki açılışta kullanılacak sürüm yapar."""
    ver = man["surum"]
    if not re.fullmatch(r"\d+(\.\d+)*", ver):
        raise UpdateError("Geçersiz sürüm adı.")
    root = ota_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{KIND}-{ver}.yeni"
    dest = root / f"{KIND}-{ver}"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members = []
        for info in z.infolist():
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name:
                raise UpdateError("Güncelleme paketinde geçersiz dosya adı.")
            if name.startswith(("organizer/", "assets/")):
                members.append(info)
        z.extractall(tmp, members)
    init = tmp / "organizer" / "__init__.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8") if init.exists() else "")
    if not m or m.group(1) != ver or not (tmp / "assets").is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        raise UpdateError("Güncelleme paketi beklenen sürümü içermiyor.")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    running = os.environ.get("ORGANIZER_OTA", "")   # şu an çalışan güncelleme (varsa): yeni sürüm açılmazsa ona dönülür
    (root / "onceki.txt").write_text(running if running != ver else "", encoding="utf-8")
    (root / "etkin.txt").write_text(ver, encoding="utf-8")
    cleanup(data_dir, keep={ver, running})
    return ver


def cleanup(data_dir, keep):
    root = ota_root(data_dir)
    if not root.is_dir():
        return
    for d in root.iterdir():
        if d.is_dir() and d.name.startswith(KIND + "-") and d.name[len(KIND) + 1:] not in keep:
            shutil.rmtree(d, ignore_errors=True)


def restart():
    """Programı yeniden açar (çağıran ardından kapanmalı)."""
    exe = Path(sys.executable).resolve()
    launcher = exe.parent.parent.parent / "Organizer.exe"   # taşınabilir: <klasör>\_sistem\python\pythonw.exe
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    if launcher.exists():
        subprocess.Popen([str(launcher)], creationflags=flags, close_fds=True)
    else:
        main = Path(sys.argv[0]).resolve()
        subprocess.Popen([sys.executable, str(main)], creationflags=flags, close_fds=True,
                         cwd=str(main.parent))


class UpdateError(Exception):
    pass


# ------------------------------------------------------------------ arka plan işleri
def _client(config, refresh):
    """Firebase istemcisi (yalnızca GitHub'a ulaşılamazsa kullanılır); hesap bağlı değilse None."""
    if not config or not refresh:
        return None
    try:
        c = FirebaseClient(config)
        c.resume(refresh)
        return c
    except Exception:  # noqa: BLE001
        return None


class _CheckWorker(QThread):
    result = Signal(object, str)   # bildirge ya da None, hata metni

    def __init__(self, config, refresh, data_dir):
        super().__init__()
        self.config, self.refresh, self.data_dir = config, refresh, data_dir

    def run(self):
        try:
            self.result.emit(check(lambda: _client(self.config, self.refresh), self.data_dir), "")
        except SyncError as e:
            from .cloud import error_text
            self.result.emit(None, error_text(e))
        except Exception as e:  # noqa: BLE001
            self.result.emit(None, str(e))


class _InstallWorker(QThread):
    progress = Signal("qint64", "qint64")
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, config, refresh, data_dir, man):
        super().__init__()
        self.config, self.refresh, self.data_dir, self.man = config, refresh, data_dir, man

    def run(self):
        try:
            blob = download(lambda: _client(self.config, self.refresh), self.man, lambda i, n: self.progress.emit(i, n))
            self.finished_ok.emit(install(self.data_dir, self.man, blob))
        except UpdateError as e:
            self.failed.emit(str(e))
        except SyncError as e:
            from .cloud import error_text
            self.failed.emit(error_text(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class Updater(QObject):
    """Güncellemeyi denetler ve kurar. state: "", "checking", "available", "none", "installing", "ready", "error"."""
    changed = Signal()

    def __init__(self, sync, parent=None):
        super().__init__(parent)
        self.sync = sync
        self.state = ""
        self.manifest = None
        self.message = ""
        self.installed = ""
        self.done = self.total = 0
        self.speed = 0.0          # bayt/sn (yumuşatılmış)
        self._t0 = self._tl = 0.0
        self._dl = 0
        self._w = None

    @property
    def version(self):
        return goster(__version__)

    def busy(self):
        return self._w is not None and self._w.isRunning()

    def check(self):
        if self.busy() or self.state == "ready":
            return
        self.state, self.message = "checking", ""
        self.changed.emit()
        self._w = _CheckWorker(self.sync.config(), self.sync.db.get_setting("fb_refresh"), self.sync.db.data_dir)
        self._w.result.connect(self._checked)
        self._w.start()

    def _checked(self, man, err):
        self.manifest = man
        if err:
            self.state, self.message = "error", err
        elif man and int(man.get("sistem") or 1) > SISTEM:
            self.state, self.message = "error", "sistem"
        else:
            self.state = "available" if man else "none"
        self.changed.emit()

    def install(self):
        if self.busy() or not self.manifest:
            return
        self.state, self.message = "installing", ""
        self.done, self.total, self.speed = 0, int(self.manifest.get("boyut") or 0), 0.0
        self._t0 = self._tl = time.monotonic()
        self._dl = 0
        self.changed.emit()
        self._w = _InstallWorker(self.sync.config(), self.sync.db.get_setting("fb_refresh"),
                                 self.sync.db.data_dir, self.manifest)
        self._w.progress.connect(self._progress)
        self._w.finished_ok.connect(self._installed)
        self._w.failed.connect(self._failed)
        self._w.start()

    def _progress(self, done, total):
        now = time.monotonic()
        dt = now - self._tl
        if done > self._dl and dt > 0:
            inst = (done - self._dl) / dt
            self.speed = inst if not self.speed else self.speed * 0.5 + inst * 0.5
        elif done and now > self._t0:
            self.speed = self.speed or done / (now - self._t0)
        self._tl, self._dl = now, done
        self.done, self.total = done, total
        self.message = f"%{self.percent()}"
        self.changed.emit()

    # ---- indirme bilgisi (ekranlar bu değerleri satır satır gösterir)
    def percent(self):
        return min(100, int(self.done * 100 / self.total)) if self.total else 0

    def eta(self):
        """Kalan süre (saniye); hız bilinmiyorsa None."""
        if not self.speed or not self.total:
            return None
        return max(0, int(round((self.total - self.done) / self.speed)))

    def _installed(self, ver):
        self.state, self.installed, self.message = "ready", ver, ""
        self.changed.emit()

    def _failed(self, text):
        self.state, self.message = "error", text
        self.changed.emit()

    def wait(self, ms=30000):
        if self._w is not None:
            self._w.wait(ms)


# ------------------------------------------------------------------ indirme bilgisinin yazımı
def _num(x, digits=1):
    from . import i18n
    s = f"{x:.{digits}f}"
    return s.replace(".", ",") if i18n.LANG == "tr" else s


def fmt_mb(b):
    return _num(b / 1048576)


def fmt_speed(bps):
    from .i18n import t
    if not bps:
        return "—"
    if bps >= 1048576:
        return t("{x} MB/sn", x=_num(bps / 1048576))
    return t("{x} KB/sn", x=_num(bps / 1024, 0))


def fmt_eta(sec):
    from .i18n import t
    if sec is None:
        return t("hesaplanıyor…")
    if sec < 60:
        return t("yaklaşık {s} sn", s=max(1, sec))
    return t("yaklaşık {m} dk {s} sn", m=sec // 60, s=sec % 60)


def progress_rows(u):
    """Updater durumundan ekranda alt alta gösterilecek (etiket, değer) satırları."""
    from .i18n import t
    return [
        (t("İnen"), t("{a} / {b} MB", a=fmt_mb(u.done), b=fmt_mb(u.total))),
        (t("Kalan"), t("{a} MB", a=fmt_mb(max(u.total - u.done, 0)))),
        (t("Hız"), fmt_speed(u.speed)),
        (t("Kalan süre"), fmt_eta(u.eta())),
    ]
