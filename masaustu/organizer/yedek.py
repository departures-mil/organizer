"""2.3.0 — Otomatik yedek, şifreli yedek ve tek tuşla geri yükleme.

* Otomatik yedek: günlük / haftalık; hedef klasör seçilebilir (ör. bilgisayardaki Google Drive klasörü
  — "Google Drive for desktop" ile o klasördeki her şey Drive'a kendiliğinden gider). Son N yedek tutulur.
* Şifre: isteğe bağlı; AES-256-GCM, anahtar şifreden PBKDF2-SHA256 (200 000 tur) ile türetilir.
  Dosya biçimi (telefonla aynı): b"OZB1" + tuz(16) + iv(12) + şifreli veri. Şifresiz yedek düz .zip'tir.
* Geri yükleme kayıt SİLMEZ: yedekteki her kayıt yeni bir değişiklik olarak yazılır (öbür cihazlara da gider);
  o an eldeki farklı hali önce Arşiv'e alınır, yedekte olmayan kayıtlar ve fotoğraflar yerinde kalır."""
import base64
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

MAGIC = b"OZB1"
ITER = 200_000
PREFIX = "Organizer-otomatik-"
FREQ_DAYS = {"off": 0, "daily": 1, "weekly": 7}
KEEP_DEFAULT = 10


class NeedPassword(Exception):
    pass


class WrongPassword(Exception):
    pass


class BadBackup(Exception):
    pass


# ------------------------------------------------------------------ şifreleme
def _key(password, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode("utf-8"))


def encrypt(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    return MAGIC + salt + iv + AESGCM(_key(password, salt)).encrypt(iv, data, None)


def decrypt(blob: bytes, password: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not is_encrypted(blob):
        return blob
    salt, iv, body = blob[4:20], blob[20:32], blob[32:]
    try:
        return AESGCM(_key(password or "", salt)).decrypt(iv, body, None)
    except InvalidTag:
        raise WrongPassword() from None


def is_encrypted(blob: bytes) -> bool:
    return blob[:4] == MAGIC


def crypto_ok():
    try:
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ ayarlar
def _pw(db):
    v = db.get_setting("auto_backup_pw", "") or ""
    try:
        return base64.b64decode(v.encode()).decode("utf-8") if v else ""
    except Exception:
        return ""


def settings(db):
    return {
        "freq": db.get_setting("auto_backup_freq", "weekly") or "weekly",
        "dir": db.get_setting("auto_backup_dir", "") or str(default_dir(db)),
        "keep": int(db.get_setting("auto_backup_keep", str(KEEP_DEFAULT)) or KEEP_DEFAULT),
        "password": _pw(db),
        "last": db.get_setting("auto_backup_last", "") or "",
    }


def save_settings(db, freq=None, folder=None, keep=None, password=None):
    if freq is not None:
        db.set_setting("auto_backup_freq", freq if freq in FREQ_DAYS else "weekly")
    if folder is not None:
        db.set_setting("auto_backup_dir", str(folder) if str(folder) != str(default_dir(db)) else "")
    if keep is not None:
        db.set_setting("auto_backup_keep", str(max(1, min(int(keep), 100))))
    if password is not None:
        db.set_setting("auto_backup_pw", base64.b64encode(password.encode("utf-8")).decode() if password else "")


def default_dir(db):
    return Path(db.data_dir) / "yedek" / "otomatik"


def due(db, now=None):
    s = settings(db)
    days = FREQ_DAYS.get(s["freq"], 7)
    if not days:
        return False
    if not s["last"]:
        return True
    try:
        last = datetime.fromisoformat(s["last"])
    except ValueError:
        return True
    return (now or datetime.now()) - last >= timedelta(days=days) - timedelta(minutes=30)


# ------------------------------------------------------------------ yedek al
def make(db, password=""):
    """Veritabanı + fotoğraflar → zip baytları (şifre varsa şifreli). Arka plan iş parçacığında da çağrılabilir:
    kendi SQLite bağlantısını açar."""
    import sqlite3
    data_dir = Path(db.data_dir)
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "organizer.db"
        src = sqlite3.connect(str(data_dir / "organizer.db"), timeout=10)
        dest = sqlite3.connect(str(snap))
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "organizer.db")
            photos = data_dir / "fotograflar"
            for f in sorted(photos.iterdir()) if photos.is_dir() else []:
                if f.is_file():
                    z.write(f, f"fotograflar/{f.name}", compress_type=zipfile.ZIP_STORED)
    data = buf.getvalue()
    return encrypt(data, password) if password else data


def run(db, now=None, s=None):
    """Otomatik yedeği yazar, eskileri temizler. Yazılan dosyanın yolunu döndürür.
    s: settings(db) (arka planda çalışırken ana iş parçacığında önceden okunur)."""
    s = s or settings(db)
    folder = Path(s["dir"])
    folder.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()
    pw = s["password"] if s["password"] and crypto_ok() else ""
    name = f"{PREFIX}{now:%Y-%m-%d_%H%M}." + ("ozb" if pw else "zip")
    target = folder / name
    tmp = folder / (name + ".tmp")
    tmp.write_bytes(make(db, pw))
    os.replace(tmp, target)
    prune(folder, s["keep"])
    return target


def list_backups(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.name.startswith(PREFIX) and p.suffix in (".zip", ".ozb")]
    return sorted(files, key=lambda p: p.name, reverse=True)


def prune(folder, keep):
    for p in list_backups(folder)[max(1, keep):]:
        try:
            p.unlink()
        except OSError:
            pass


# ------------------------------------------------------------------ geri yükle
def read(path, password=None):
    """Yedek dosyasını okur, zip baytlarını döndürür. Şifreliyse ve şifre yoksa NeedPassword."""
    blob = Path(path).read_bytes()
    if is_encrypted(blob):
        if not password:
            raise NeedPassword()
        blob = decrypt(blob, password)
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        raise BadBackup("zip")
    return blob


def restore(db, zip_bytes):
    """Yedekteki kayıtları geri getirir (bkz. modül açıklaması). {tablo: geri gelen kayıt sayısı} döndürür."""
    from .db import Database, SYNC_TABLES, _later_than, _same_record
    counts = {}
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            names = z.namelist()
            root = next((n[: -len("organizer.db")] for n in names if n.endswith("organizer.db")), None)
            if root is None:
                raise BadBackup("organizer.db")
            z.extractall(tmp)
        src_dir = Path(tmp) / root if root else Path(tmp)
        src = Database(src_dir)
        try:
            recs = src.all_records()
        finally:
            src.conn.close()
        photo_src = src_dir / "fotograflar"
        for p in (photo_src.iterdir() if photo_src.is_dir() else []):
            if p.is_file() and not (db.photos_dir / p.name).exists():
                shutil.copy2(p, db.photos_dir / p.name)
        # pre-safety: o anki hali yedekle (veri klasörü\yedek\geri-yukleme-oncesi-*.zip, son 5)
        safety = Path(db.data_dir) / "yedek"
        safety.mkdir(parents=True, exist_ok=True)
        db.backup(safety / f"geri-yukleme-oncesi-{datetime.now():%Y-%m-%d_%H%M%S}.zip")
        olds = sorted(safety.glob("geri-yukleme-oncesi-*.zip"), reverse=True)
        for p in olds[5:]:
            try:
                p.unlink()
            except OSError:
                pass
        for table in SYNC_TABLES:
            out, touched = [], []
            for rec in recs.get(table, []):
                if rec.get("deleted"):
                    continue
                row = db.conn.execute(f"SELECT id, mtime, deleted FROM {table} WHERE uid=?", (rec["uid"],)).fetchone()
                cur = db._export_one(table, row["id"]) if row is not None else None
                if cur is not None and not cur.get("deleted"):
                    if _same_record(cur, rec) and not (table == "items" and cur.get("trashed_at")):
                        continue
                    db._archive_local(table, row["id"], "yedek_oncesi")
                    if table in ("items", "contacts"):   # eldeki fotoğraflar silinmesin
                        rec["photos"] = list(rec.get("photos") or []) + \
                            [p for p in cur.get("photos") or [] if p not in (rec.get("photos") or [])]
                    touched.append(row["id"])
                if table == "items":
                    rec["trashed_at"] = ""
                rec["photos"] = [p for p in rec.get("photos") or [] if (db.photos_dir / p).exists()] \
                    if table in ("items", "contacts") else rec.get("photos")
                rec["mtime"] = _later_than(row["mtime"] if row is not None else "")
                rec["deleted"] = False
                out.append(rec)
            if not out:
                continue
            before = db._state(touched) if table == "items" else {}
            with db.conn:   # eski hal zaten arşivde: apply_remote ikinci bir "çakışma" kaydı açmasın
                db.conn.executemany(f"UPDATE {table} SET dirty=0 WHERE id=?", [(i,) for i in touched])
            db.apply_remote(table, out, keep_dirty=True)
            if table == "items":
                db._log(before, "yedekten")
                ids = {r[0] for r in db.conn.execute("SELECT id FROM items WHERE uid IN (%s)" % ",".join("?" * len(out)),
                                                     [r["uid"] for r in out])}
                for i in ids - set(touched):
                    db._log_created(i)
            counts[table] = len(out)
    return counts


def summary(counts, t):
    names = {"items": t("Eşya"), "contacts": t("Usta / dükkan"), "locations": t("Yer"), "categories": t("Kategori")}
    parts = [f"{names[k]}: {v}" for k, v in counts.items() if v]
    return ", ".join(parts) if parts else t("Yedekteki kayıtlar zaten bu cihazdakiyle aynı.")


def export_settings(db):
    """(Test ve hata ayıklama için) ayarlar JSON."""
    s = settings(db)
    s["password"] = bool(s["password"])
    return json.dumps(s, ensure_ascii=False)
