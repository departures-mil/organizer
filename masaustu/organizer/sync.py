"""Firebase (Firestore) üzerinden telefon ve bilgisayar arasında eşitleme.

Yalnızca Firebase'in REST arayüzleri kullanılır, ek kütüphane gerekmez:
  - Kimlik doğrulama: e-posta + şifre (Identity Toolkit)
  - Veriler: Firestore, users/{kullanıcı}/{locations|categories|items|contacts|photos}/{uid}
  - Fotoğraflar: Firestore belgesi içinde (en fazla ~900 KB JPEG), ücretsiz planda çalışsın diye

Kurallar: son değiştirilen kazanır (mtime), silinenler "deleted" işaretiyle yayılır.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .db import SYNC_TABLES, Database

MAX_PHOTO_BYTES = 900_000
PHOTO_MAX_SIDE = 1600


class SyncError(Exception):
    """code: config | auth | network | server"""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def parse_config(text):
    """Firebase konsolundaki firebaseConfig parçasından apiKey ve projectId'yi çıkarır."""
    text = text or ""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("apiKey") and data.get("projectId"):
            return {"apiKey": data["apiKey"], "projectId": data["projectId"]}
    except ValueError:
        pass
    out = {}
    for key in ("apiKey", "projectId"):
        m = re.search(key + r"""\s*["']?\s*:\s*["']([^"']+)["']""", text)
        if m:
            out[key] = m.group(1).strip()
    if not out.get("apiKey") or not out.get("projectId"):
        raise SyncError("config")
    return out


# ---------------------------------------------------------------- Firestore değer dönüşümü
def to_value(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (bytes, bytearray)):
        return {"bytesValue": base64.b64encode(v).decode()}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [to_value(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: to_value(x) for k, x in v.items()}}}
    return {"stringValue": str(v)}


def from_value(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "bytesValue" in v:
        return base64.b64decode(v["bytesValue"])
    if "arrayValue" in v:
        return [from_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: from_value(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def ts_key(ts):
    """Firestore zaman damgalarını karşılaştırılabilir hale getirir (kesir hanesi değişken olabilir)."""
    if not ts:
        return ""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z?$", ts)
    if not m:
        return ts
    return m.group(1) + "." + (m.group(2) or "").ljust(9, "0")[:9]


class FirebaseClient:
    def __init__(self, config, emulator=None):
        self.api_key = config["apiKey"]
        self.project = config["projectId"]
        emulator = emulator or os.environ.get("ORGANIZER_FIREBASE_EMULATOR")
        if emulator:
            emulator = emulator.rstrip("/")
            self.auth_base = f"{emulator}/identitytoolkit/v1"
            self.token_url = f"{emulator}/securetoken/v1/token"
            self.fs_root = f"{emulator}/firestore/v1"
        else:
            self.auth_base = "https://identitytoolkit.googleapis.com/v1"
            self.token_url = "https://securetoken.googleapis.com/v1/token"
            self.fs_root = "https://firestore.googleapis.com/v1"
        self.db_path = f"projects/{self.project}/databases/(default)/documents"
        self.id_token = None
        self.expires = 0
        self.refresh_token = None
        self.uid = None
        self.email = None

    # ------------------------------------------------------------ http
    def _request(self, method, url, body=None, form=False, auth=True):
        headers = {}
        data = None
        if body is not None:
            if form:
                data = urllib.parse.urlencode(body).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self._token()}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
                msg = err.get("error", {}).get("message", "") if isinstance(err.get("error"), dict) \
                    else str(err.get("error", ""))
            except Exception:
                msg = ""
            if e.code == 404:
                raise SyncError("not_found", msg)
            if not auth or e.code in (401, 403):
                raise SyncError("auth", msg or str(e.code))
            raise SyncError("server", msg or str(e.code))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SyncError("network", str(e))

    # ------------------------------------------------------------ kimlik
    def _set_session(self, id_token, refresh_token, uid, expires_in, email=None):
        self.id_token, self.refresh_token, self.uid = id_token, refresh_token, uid
        self.expires = time.time() + int(expires_in) - 120
        if email:
            self.email = email

    def sign_in(self, email, password, create=False):
        op = "signUp" if create else "signInWithPassword"
        r = self._request("POST", f"{self.auth_base}/accounts:{op}?key={self.api_key}",
                          {"email": email, "password": password, "returnSecureToken": True}, auth=False)
        self._set_session(r["idToken"], r["refreshToken"], r["localId"], r.get("expiresIn", 3600),
                          r.get("email", email))

    def resume(self, refresh_token):
        self.refresh_token = refresh_token
        self._refresh()

    def _refresh(self):
        r = self._request("POST", f"{self.token_url}?key={self.api_key}",
                          {"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                          form=True, auth=False)
        self._set_session(r["id_token"], r["refresh_token"], r["user_id"], r.get("expires_in", 3600))

    def _token(self):
        if not self.id_token or time.time() > self.expires:
            if not self.refresh_token:
                raise SyncError("auth", "not signed in")
            self._refresh()
        return self.id_token

    # ------------------------------------------------------------ firestore
    def _doc_name(self, collection, doc_id):
        return f"{self.db_path}/users/{self.uid}/{collection}/{doc_id}"

    def commit(self, writes):
        if writes:
            self._request("POST", f"{self.fs_root}/{self.db_path}:commit", {"writes": writes})

    def upsert_write(self, collection, doc_id, fields):
        return {"update": {"name": self._doc_name(collection, doc_id),
                           "fields": {k: to_value(v) for k, v in fields.items()}},
                "updateTransforms": [{"fieldPath": "synced_at", "setToServerValue": "REQUEST_TIME"}]}

    def delete_write(self, collection, doc_id):
        return {"delete": self._doc_name(collection, doc_id)}

    def changed_since(self, collection, cursor):
        query = {"from": [{"collectionId": collection}],
                 "orderBy": [{"field": {"fieldPath": "synced_at"}, "direction": "ASCENDING"}]}
        if cursor:
            query["where"] = {"fieldFilter": {"field": {"fieldPath": "synced_at"}, "op": "GREATER_THAN",
                                              "value": {"timestampValue": cursor}}}
        res = self._request("POST", f"{self.fs_root}/{self.db_path}/users/{self.uid}:runQuery",
                            {"structuredQuery": query})
        out = []
        for row in res:
            doc = row.get("document")
            if doc:
                fields = {k: from_value(v) for k, v in doc.get("fields", {}).items()}
                fields["uid"] = doc["name"].rsplit("/", 1)[-1]
                out.append(fields)
        return out

    def get(self, collection, doc_id):
        try:
            doc = self._request("GET", f"{self.fs_root}/{self._doc_name(collection, doc_id)}")
        except SyncError as e:
            if e.code == "not_found":
                return None
            raise
        return {k: from_value(v) for k, v in doc.get("fields", {}).items()}

    def get_doc(self, path):
        """Kullanıcı klasörü dışındaki bir belge (ör. "guncelleme/masaustu"); yoksa None."""
        try:
            doc = self._request("GET", f"{self.fs_root}/{self.db_path}/{path}")
        except SyncError as e:
            if e.code == "not_found":
                return None
            raise
        return {k: from_value(v) for k, v in doc.get("fields", {}).items()}


def photo_bytes(path):
    """Fotoğrafı buluta uygun boyutta JPEG'e çevirir (Firestore belge sınırı 1 MB)."""
    raw = path.read_bytes()
    if len(raw) <= MAX_PHOTO_BYTES and raw[:3] == b"\xff\xd8\xff":
        return raw
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImageReader
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    img = reader.read()
    if img.isNull():
        return None
    side = PHOTO_MAX_SIDE
    while True:
        scaled = img if max(img.width(), img.height()) <= side else \
            img.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for quality in (85, 75, 65, 55):
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            scaled.save(buf, "JPG", quality)
            buf.close()
            if ba.size() <= MAX_PHOTO_BYTES:
                return bytes(ba)
        side = int(side * 0.75)


def sync(db: Database, client: FirebaseClient, progress=None):
    """Tam eşitleme: önce buluttaki değişiklikleri al, sonra yerel değişiklikleri gönder,
    sonra fotoğrafları yükle/indir. {'received': n, 'sent': n} döndürür."""
    say = progress or (lambda *_: None)
    received = sent = 0

    # 1) al
    for table in SYNC_TABLES:
        say("pull", table)
        cursor = db.get_setting(f"sync_cursor_{table}")
        docs = client.changed_since(table, cursor)
        if docs:
            received += db.apply_remote(table, docs)
            newest = max((d.get("synced_at") for d in docs if d.get("synced_at")), key=ts_key, default=None)
            if newest and ts_key(newest) > ts_key(cursor):
                db.set_setting(f"sync_cursor_{table}", newest)

    # 2) gönder
    dirty = db.dirty_records()
    for table in SYNC_TABLES:
        recs = dirty[table]
        for i in range(0, len(recs), 200):
            chunk = recs[i:i + 200]
            say("push", table)
            client.commit([client.upsert_write(table, r["uid"], {k: v for k, v in r.items() if k != "uid"})
                           for r in chunk])
            for r in chunk:
                db.mark_clean(table, r["uid"], r["mtime"])
            sent += len(chunk)

    # 3) fotoğraflar
    for fname in db.photos_to_delete():
        try:
            client.commit([client.delete_write("photos", fname)])
        except SyncError as e:
            if e.code != "not_found":
                raise
        db.set_photo_state(fname, None)
    for fname, item_uid in db.photos_to_upload():
        say("photo_up", fname)
        data = photo_bytes(db.photos_dir / fname)
        if data is None:
            db.set_photo_state(fname, "bad")
            continue
        client.commit([client.upsert_write("photos", fname, {"data": data, "item": item_uid})])
        db.set_photo_state(fname, "up")
    for fname in db.missing_photos():
        say("photo_down", fname)
        doc = client.get("photos", fname)
        if doc and doc.get("data"):
            (db.photos_dir / fname).write_bytes(doc["data"])
            db.set_photo_state(fname, "up")
    return {"received": received, "sent": sent}
