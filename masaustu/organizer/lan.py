"""Yerel ağ (aynı modem / router) üzerinden eşitleme — internet gerekmez (v.1.0.8).

Bilgisayar, açık olduğu sürece aynı ağdaki telefon ve bilgisayarları bekler:
  - Bulma: UDP 47322'ye "ORGANIZER-LAN?" yayını → {"app": "organizer-lan", "name", "port", "version"} yanıtı
  - Eşitleme: HTTP 47321, JSON
      POST /organizer/lan/sync   {key, device, records: {tablo: [kayıt]}, have: [fotoğraf]}
           → {records: {tablo: [kayıt]}, have: [fotoğraf], need: [fotoğraf], name}
      POST /organizer/lan/photo  {key, name}            → {data: base64}
      POST /organizer/lan/upload {key, name, data}      → {ok: true}
Kayıtlar Firebase eşitlemesiyle aynı ortak biçimdedir ve aynı kuralla birleştirilir: her kayıtta son
değiştirilen kazanır (mtime), silinenler "silindi" işaretiyle yayılır; hiçbir kayıt üzerine körü körüne
yazılmaz. Yerel ağdan gelen değişiklikler buluta da gönderilmek üzere işaretli kalır.
Anahtar: bilgisayardaki 6 haneli eşleme kodu, ya da iki cihaz aynı bulut hesabına bağlıysa hesaptan
türetilen anahtar (o zaman kod sorulmaz).
"""
import base64
import hashlib
import json
import random
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .db import SYNC_TABLES, Database, now_str

HTTP_PORT = 47321
UDP_PORT = 47322
PROBE = b"ORGANIZER-LAN?"
MAX_BODY = 60 * 1024 * 1024


def uid_key(fb_uid):
    """Aynı bulut hesabındaki cihazlar için ortak anahtar (kod sormadan eşleşirler)."""
    return hashlib.sha256(f"organizer-lan:{fb_uid}".encode()).hexdigest()[:24] if fb_uid else ""


def local_ips():
    """Bu bilgisayarın yerel ağ adresleri (192.168.x.x gibi)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # paket gönderilmez; yalnızca hangi arayüzün kullanılacağı bulunur
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return [ip for ip in out if not ip.startswith("127.")]


def device_name():
    try:
        return socket.gethostname() or "Organizer"
    except OSError:
        return "Organizer"


def lan_backup(db: Database):
    """Yerel ağdan değişiklik almadan önce günde bir kez veritabanı yedeği (son 5 gün tutulur)."""
    folder = db.data_dir / "yedek"
    folder.mkdir(exist_ok=True)
    target = folder / f"organizer-yerel-ag-oncesi-{datetime.now():%Y-%m-%d}.db"
    if target.exists():
        return
    import sqlite3
    dest = sqlite3.connect(str(target))
    db.conn.backup(dest)
    dest.close()
    for old in sorted(folder.glob("organizer-yerel-ag-oncesi-*.db"))[:-5]:
        try:
            old.unlink()
        except OSError:
            pass


def merge(db: Database, records):
    """Gelen kayıtları birleştirir; değişen kayıt sayısını döndürür."""
    n = 0
    for table in SYNC_TABLES:
        recs = [r for r in (records or {}).get(table) or [] if isinstance(r, dict) and r.get("uid")]
        if recs:
            n += db.apply_remote(table, recs, keep_dirty=True)
    return n


def referenced_photos(db: Database):
    return {r[0] for r in db.conn.execute(db._ALL_PHOTOS)}


# ====================================================================== sunucu
class LanServer(QObject):
    """Bilgisayarda arka planda çalışan yerel ağ sunucusu."""
    data_changed = Signal()       # başka cihazdan yeni kayıt geldi
    state_changed = Signal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.data_dir = db.data_dir
        self.httpd = None
        self.udp = None
        self.error = ""
        self.last = ""
        if not db.get_setting("lan_code"):
            db.set_setting("lan_code", f"{random.SystemRandom().randint(0, 999999):06d}")

    # ------------------------------------------------------------ ayarlar
    def code(self):
        return self.db.get_setting("lan_code", "")

    def new_code(self):
        self.db.set_setting("lan_code", f"{random.SystemRandom().randint(0, 999999):06d}")
        self.state_changed.emit(self.status_text())

    def enabled(self):
        return self.db.get_setting("lan_server", "1") == "1"

    def running(self):
        return self.httpd is not None

    def keys(self):
        """Geçerli anahtarlar. Sunucu iş parçacığından çağrılır: kendi bağlantısıyla okur."""
        import sqlite3
        conn = sqlite3.connect(str(self.data_dir / "organizer.db"), timeout=5)
        try:
            s = dict(conn.execute("SELECT key, value FROM settings WHERE key IN ('lan_code', 'fb_uid')").fetchall())
        finally:
            conn.close()
        return {x for x in (s.get("lan_code"), uid_key(s.get("fb_uid"))) if x}

    def status_text(self):
        from .i18n import t
        if not self.enabled():
            return t("Yerel ağ eşitlemesi kapalı.")
        if self.error:
            return "⚠ " + self.error
        if not self.running():
            return t("Yerel ağ eşitlemesi başlatılıyor…")
        ips = ", ".join(f"{ip}:{HTTP_PORT}" for ip in local_ips()) or t("(ağ bağlantısı yok)")
        text = t("Bu bilgisayar aynı ağdaki cihazları bekliyor: {a}", a=ips)
        last = self.db.get_setting("lan_last")
        if last:
            text += "\n" + t("Son yerel ağ eşitlemesi: {d}", d=last)
        return text

    # ------------------------------------------------------------ başlat / durdur
    def start(self):
        if self.running() or not self.enabled():
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(raw)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if self.path.startswith("/organizer/lan/info"):
                    from . import __version__
                    self._send(200, {"app": "organizer-lan", "name": device_name(), "version": __version__})
                else:
                    self._send(404, {"error": "not_found"})

            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > MAX_BODY:
                        return self._send(413, {"error": "size"})
                    body = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, OSError):
                    return self._send(400, {"error": "bad_request"})
                if str(body.get("key") or "") not in server.keys():
                    return self._send(401, {"error": "key"})
                try:
                    out = server.handle(self.path.split("?")[0], body)
                except Exception as e:   # tek bir istek sunucuyu düşürmesin
                    return self._send(500, {"error": str(e)})
                if out is None:
                    return self._send(404, {"error": "not_found"})
                self._send(200, out)

        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
            self.httpd.daemon_threads = True
        except OSError as e:
            from .i18n import t
            self.httpd = None
            self.error = t("Yerel ağ kapısı ({p}) açılamadı: {m}", p=HTTP_PORT, m=e.strerror or str(e))
            self.state_changed.emit(self.status_text())
            return
        self.error = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self._udp_loop, daemon=True).start()
        self.state_changed.emit(self.status_text())

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except OSError:
                pass
            self.httpd = None
        if self.udp:
            try:
                self.udp.close()
            except OSError:
                pass
            self.udp = None
        self.state_changed.emit(self.status_text())

    def set_enabled(self, on):
        self.db.set_setting("lan_server", "1" if on else "0")
        self.start() if on else self.stop()
        self.state_changed.emit(self.status_text())

    def _udp_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", UDP_PORT))
        except OSError:
            return
        self.udp = sock
        from . import __version__
        while self.httpd is not None:
            try:
                data, addr = sock.recvfrom(512)
            except OSError:
                break
            if data.strip().startswith(PROBE):
                reply = json.dumps({"app": "organizer-lan", "name": device_name(), "port": HTTP_PORT,
                                    "version": __version__}).encode()
                try:
                    sock.sendto(reply, addr)
                except OSError:
                    pass

    # ------------------------------------------------------------ istekler (sunucu iş parçacığında)
    _lock = threading.Lock()

    def handle(self, path, body):
        if path == "/organizer/lan/sync":
            with self._lock:
                db = Database(self.data_dir)
                try:
                    lan_backup(db)
                    changed = merge(db, body.get("records"))
                    have = db.photo_names()
                    refs = referenced_photos(db)
                    theirs = set(body.get("have") or [])
                    out = {"records": db.all_records(), "have": sorted(have & refs),
                           "need": sorted((refs - have) & theirs), "name": device_name(), "received": changed}
                    db.set_setting("lan_last", f"{now_str()[:16]} · {str(body.get('device') or '')[:40]}")
                finally:
                    db.conn.close()
            if changed:
                self.data_changed.emit()
            self.state_changed.emit("")   # alıcılar durumu ana iş parçacığında status_text() ile okur
            return out
        if path == "/organizer/lan/photo":
            name = Path(str(body.get("name") or "")).name
            f = self.data_dir / "fotograflar" / name
            if not name or not f.is_file():
                return {"data": None}
            return {"data": base64.b64encode(f.read_bytes()).decode()}
        if path == "/organizer/lan/upload":
            name = Path(str(body.get("name") or "")).name
            data = body.get("data")
            if not name or not data:
                return {"ok": False}
            f = self.data_dir / "fotograflar" / name
            if not f.exists():
                tmp = f.with_suffix(f.suffix + ".part")
                tmp.write_bytes(base64.b64decode(data))
                shutil.move(str(tmp), str(f))
                self.data_changed.emit()
            return {"ok": True}
        return None


# ====================================================================== istemci (başka bir bilgisayarla eşitleme)
class LanError(Exception):
    """code: key | network | server"""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def discover(timeout=1.6):
    """Aynı ağdaki Organizer bilgisayarlarını bulur: [{"host", "port", "name", "version"}]."""
    found = {}
    mine = set(local_ips())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    targets = {"255.255.255.255"}
    for ip in mine:
        parts = ip.split(".")
        if len(parts) == 4:
            targets.add(".".join(parts[:3] + ["255"]))
    end = time.time() + timeout
    sent = 0
    while time.time() < end:
        if sent < 3:
            for tgt in targets:
                try:
                    sock.sendto(PROBE, (tgt, UDP_PORT))
                except OSError:
                    pass
            sent += 1
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            info = json.loads(data)
        except ValueError:
            continue
        if info.get("app") == "organizer-lan" and addr[0] not in mine:
            found[addr[0]] = {"host": addr[0], "port": int(info.get("port") or HTTP_PORT),
                              "name": info.get("name") or addr[0], "version": info.get("version") or ""}
    sock.close()
    return list(found.values())


def _post(host, port, path, body, timeout=60):
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise LanError("key" if e.code == 401 else "server", str(e.code))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LanError("network", str(e))


def sync_with(db: Database, host, port, key, progress=None):
    """Bu bilgisayarı yerel ağdaki başka bir Organizer bilgisayarıyla eşitler. {received, sent, photos}"""
    say = progress or (lambda *_: None)
    say("sync")
    have = db.photo_names() & referenced_photos(db)
    res = _post(host, port, "/organizer/lan/sync", {"key": key, "device": device_name(),
                                                     "records": db.all_records(), "have": sorted(have)})
    lan_backup(db)
    received = merge(db, res.get("records"))
    sent = 0
    for name in res.get("need") or []:
        f = db.photos_dir / Path(name).name
        if f.is_file():
            say("photo_up", name)
            _post(host, port, "/organizer/lan/upload", {"key": key, "name": f.name,
                                                         "data": base64.b64encode(f.read_bytes()).decode()})
            sent += 1
    theirs = set(res.get("have") or [])
    photos = 0
    for name in sorted((referenced_photos(db) - db.photo_names()) & theirs):
        say("photo_down", name)
        r = _post(host, port, "/organizer/lan/photo", {"key": key, "name": name})
        if r.get("data"):
            (db.photos_dir / Path(name).name).write_bytes(base64.b64decode(r["data"]))
            photos += 1
    db.set_setting("lan_last", f"{now_str()[:16]} · {res.get('name') or host}")
    return {"received": received, "sent": sent, "photos": photos}


class LanClientWorker(QThread):
    done = Signal(dict)
    failed = Signal(str, str)   # kod, ayrıntı

    def __init__(self, data_dir, host, port, key):
        super().__init__()
        self.data_dir, self.host, self.port, self.key = data_dir, host, port, key

    def run(self):
        try:
            db = Database(self.data_dir)
            try:
                self.done.emit(sync_with(db, self.host, self.port, self.key))
            finally:
                db.conn.close()
        except LanError as e:
            self.failed.emit(e.code, e.detail)
        except Exception as e:
            self.failed.emit("server", str(e))
