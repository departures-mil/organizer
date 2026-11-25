import json
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TREE_TABLES = ("locations", "categories")

CURRENCIES = [
    ("TRY", "₺", "Türk Lirası"),
    ("USD", "$", "ABD Doları"),
    ("SYP", "SYP", "Suriye Lirası"),
]
CURRENCY_NAMES = {code: name for code, _, name in CURRENCIES}

DEFAULT_LOCATIONS = [
    ("Salon", []),
    ("Mutfak", []),
    ("Balkon", ["Balkon dolabı"]),
    ("Banyo", []),
    ("Banyo üstü", []),
    ("Misafir odası", []),
    ("Çocuk odası", []),
    ("Yatak odası", []),
    ("Koridor", []),
    ("Kiler / Depo", []),
]

DEFAULT_CATEGORIES = [
    ("Hırdavat", ["Vidalar", "Somunlar", "Pullar", "Çiviler", "Dübeller", "Menteşeler"]),
    ("Elektrik", ["Kablolar", "Konektörler", "Prizler ve fişler", "Ampuller", "Piller"]),
    ("Aletler", ["El aletleri", "Elektrikli aletler", "Ölçü aletleri"]),
    ("Tesisat", ["Musluk ve bataryalar", "Contalar", "Hortumlar"]),
    ("Boya ve yapıştırıcı", []),
    ("Mutfak eşyaları", []),
    ("Ivır zıvır", []),
]

# Eşitleme alanları: uid (cihazlar arası kimlik), mtime (UTC değişiklik zamanı),
# deleted (silindi işareti), dirty (buluta gönderilmedi).
SYNC_COLS = "uid TEXT, mtime TEXT NOT NULL DEFAULT '2000-01-01T00:00:00.000Z', " \
            "deleted INTEGER NOT NULL DEFAULT 0, dirty INTEGER NOT NULL DEFAULT 1"
SEED_MTIME = "2000-01-01T00:00:00.000Z"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS locations(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES locations(id) ON DELETE CASCADE,
    sort INTEGER NOT NULL DEFAULT 0,
    {SYNC_COLS}
);
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    sort INTEGER NOT NULL DEFAULT 0,
    {SYNC_COLS}
);
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price REAL,
    currency TEXT NOT NULL DEFAULT 'TRY',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    shop_name TEXT NOT NULL DEFAULT '',
    shop_place TEXT NOT NULL DEFAULT '',
    shop_phone TEXT NOT NULL DEFAULT '',
    shop_whatsapp INTEGER NOT NULL DEFAULT 0,
    shop_telegram INTEGER NOT NULL DEFAULT 0,
    price_auto INTEGER NOT NULL DEFAULT 0,
    trashed_at TEXT NOT NULL DEFAULT '',
    min_qty INTEGER NOT NULL DEFAULT 0,
    to_buy INTEGER NOT NULL DEFAULT 0,
    loan_to TEXT NOT NULL DEFAULT '',
    loan_phone TEXT NOT NULL DEFAULT '',
    loan_date TEXT NOT NULL DEFAULT '',
    loan_due TEXT NOT NULL DEFAULT '',
    loan_history TEXT NOT NULL DEFAULT '[]',
    warranty_until TEXT NOT NULL DEFAULT '',
    expires_on TEXT NOT NULL DEFAULT '',
    changelog TEXT NOT NULL DEFAULT '[]',
    {SYNC_COLS}
);
CREATE TABLE IF NOT EXISTS item_photos(
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contacts(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'usta',
    name TEXT NOT NULL,
    profession TEXT NOT NULL DEFAULT '',
    place TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    has_whatsapp INTEGER NOT NULL DEFAULT 0,
    has_telegram INTEGER NOT NULL DEFAULT 0,
    has_call INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    jobs TEXT NOT NULL DEFAULT '[]',
    {SYNC_COLS}
);
CREATE TABLE IF NOT EXISTS contact_photos(
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS photo_sync(filename TEXT PRIMARY KEY, state TEXT NOT NULL);
-- 2.2.0 eşitleme kuralı: hiçbir kayıt kalıcı silinmez. Başka cihazda silinen kayıt (tur='silindi'), eşitlemede üstüne
-- yazılan gönderilmemiş değişiklik (tur='cakisma') ve çöp kutusundan temizlenen kayıt (tur='temizlendi') burada durur.
CREATE TABLE IF NOT EXISTS arsiv(
    id INTEGER PRIMARY KEY AUTOINCREMENT, tablo TEXT NOT NULL, uid TEXT NOT NULL, tur TEXT NOT NULL,
    kaynak TEXT NOT NULL DEFAULT '', zaman TEXT NOT NULL, ad TEXT NOT NULL DEFAULT '', veri TEXT NOT NULL,
    geri_alindi TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_items_cat ON items(category_id);
CREATE INDEX IF NOT EXISTS ix_items_loc ON items(location_id);
CREATE INDEX IF NOT EXISTS ix_photos_item ON item_photos(item_id);
CREATE INDEX IF NOT EXISTS ix_photos_contact ON contact_photos(contact_id);
"""
SYNC_TABLES = ("locations", "categories", "items", "contacts")
# 1.4.0: eşyanın satın alındığı yer (dükkan adı, yeri, numarası ve numaranın çalıştığı uygulamalar)
SHOP_TEXT = ("shop_name", "shop_place", "shop_phone")
SHOP_FLAGS = ("shop_whatsapp", "shop_telegram")
SHOP_FIELDS = SHOP_TEXT + SHOP_FLAGS

# price_auto = 1: fiyat otomatik (tahminle) girildi, kullanıcı henüz kontrol etmedi.
# 2026-11-18 ~00:10 UTC'de fiyatı boş eşyalara toplu tahmini fiyat yazıldı; o işlemin yedeği:
AUTO_PRICE_BACKUP = "organizer-yedek-fiyatlardan-once-2026-11-18.db"
AUTO_PRICE_BATCH = ("2026-11-17T23:30", "2026-11-18T00:30")   # toplu işlemin mtime aralığı (UTC)

# v.1.0.8: çöp kutusu, stok uyarısı / alışveriş listesi, ödünç takibi, usta iş geçmişi.
# Eski sürümden gelen kayıtta bu alanlar yoksa yereldeki değer korunur (apply_remote).
#   alan: (sqlite tanımı, varsayılan, tür)  tür: s=metin, i=tamsayı, b=evet/hayır, j=JSON liste
ITEM_EXTRA = {
    "trashed_at": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "min_qty": ("INTEGER NOT NULL DEFAULT 0", 0, "i"),
    "to_buy": ("INTEGER NOT NULL DEFAULT 0", False, "b"),
    "loan_to": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "loan_phone": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "loan_date": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "loan_due": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "loan_history": ("TEXT NOT NULL DEFAULT '[]'", [], "j"),
    # 2.3.0: garanti bitişi ve son kullanma tarihi (YYYY-AA-GG) + değişiklik geçmişi (kim, hangi cihaz, ne değişti)
    "warranty_until": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "expires_on": ("TEXT NOT NULL DEFAULT ''", "", "s"),
    "changelog": ("TEXT NOT NULL DEFAULT '[]'", [], "j"),
}
CHANGELOG_MAX = 40
# değişiklik geçmişinde izlenen alanlar (ortak biçimdeki adlarıyla)
TRACKED = ("name", "quantity", "category", "location", "price", "currency", "notes", "shop_name", "shop_place",
           "shop_phone", "min_qty", "to_buy", "loan_to", "loan_due", "trashed_at", "warranty_until", "expires_on",
           "photos", "price_auto")
CONTACT_EXTRA = {
    "jobs": ("TEXT NOT NULL DEFAULT '[]'", [], "j"),
}
TRASH_DAYS = 30
RECEIPT_PREFIX = "fis-"   # fatura / fiş fotoğrafları: dosya adı bu ekle başlar (eşitlemede sıradan fotoğraf gibi gider)


def is_receipt(fname) -> bool:
    return str(fname or "").startswith(RECEIPT_PREFIX)


def _extra_to_db(kind, v):
    """Ortak biçimdeki değeri SQLite sütununa çevirir."""
    import json
    if kind == "j":
        return json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)
    if kind == "i":
        try:
            return max(0, int(v or 0))
        except (TypeError, ValueError):
            return 0
    if kind == "b":
        return int(bool(v))
    return str(v or "")


def _extra_from_db(kind, v):
    import json
    if kind == "j":
        try:
            d = json.loads(v or "[]")
            return d if isinstance(d, list) else []
        except ValueError:
            return []
    if kind == "i":
        return int(v or 0)
    if kind == "b":
        return bool(v)
    return v or ""


def _short(v):
    """Değişiklik geçmişinde gösterilecek kısa değer."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    if isinstance(v, list):
        return str(len(v))
    return str(v).replace("\n", " ").strip()[:80]


def merge_changelog(a, b):
    """İki cihazın değişiklik geçmişini birleştirir (aynı kayıt bir kez), zamana göre sıralar, son CHANGELOG_MAX kalır."""
    out, seen = [], set()
    for e in sorted([x for x in list(a or []) + list(b or []) if isinstance(x, dict)], key=lambda e: str(e.get("t", ""))):
        k = (e.get("t"), e.get("d"), e.get("a"), json.dumps(e.get("c"), ensure_ascii=False, sort_keys=True))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out[-CHANGELOG_MAX:]


def norm_day(v) -> str:
    """'2026-12-31', '31.12.2026' → '2026-12-31'; geçersizse boş."""
    v = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", v) or None
    if m:
        y, mo, d = m.groups()
    else:
        m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", v)
        if not m:
            return ""
        d, mo, y = m.groups()
    try:
        return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

_UPPER_TR = str.maketrans({"İ": "i", "I": "ı"})
_FOLD_TR = str.maketrans("ıçğöşüâîûأإآٱةى", "icgosuaiuااااهي")
_AR_MARKS = dict.fromkeys(range(0x064B, 0x0653))  # Arapça hareke işaretleri


def norm(text) -> str:
    """Harf farklarına duyarsız arama için metni sadeleştirir (Çivi -> civi, أ -> ا)."""
    return (text or "").translate(_UPPER_TR).lower().translate(_FOLD_TR).translate(_AR_MARKS).replace("ـ", "")


# Sesli / yazılı soru sözcükleri: "Matkap nerede?" aramasında yalnızca "matkap" aranır.
QUESTION_WORDS = {norm(w) for w in (
    "nerede", "nerde", "neredeydi", "nerededir", "nereye", "koydum", "koymuştum", "benim", "acaba", "hani", "var", "mı", "mi",
    "where", "is", "are", "the", "my", "did", "i", "put", "a", "an",
    "أين", "اين", "وين", "فين", "هو", "هي", "ال")}
QUESTION_MARKS = {norm(w) for w in ("nerede", "nerde", "neredeydi", "nerededir", "where", "أين", "اين", "وين", "فين")}
ADD_WORDS = {norm(w) for w in ("ekle", "ekleyin", "kaydet", "yeni", "add", "new", "save", "أضف", "اضف", "زد", "جديد", "سجل")}


def term_in(term, hay):
    """Arama sözcüğü metinde var mı? Arapçadaki "ال" takısı olmadan da denenir (المثقاب → مثقاب)."""
    return term in hay or (len(term) > 3 and term.startswith("ال") and term[2:] in hay)


def parse_voice(text):
    """Sesli komut: {"intent": "where"|"add"|"search", "query": metin, "qty": adet ya da None}.
    "matkap nerede" → where/matkap · "3 ampul ekle" → add/ampul, 3 · "matkap" → search."""
    raw = re.sub(r"[?؟!.,،]+", " ", text or "").strip()
    words = raw.split()
    nw = [norm(w) for w in words]
    intent = "search"
    if any(w in QUESTION_MARKS for w in nw):
        intent = "where"
    elif any(w in ADD_WORDS for w in nw):
        intent = "add"
    qty = None
    keep = []
    for w, n in zip(words, nw):
        if intent == "add" and n in ADD_WORDS:
            continue
        if intent == "where" and n in QUESTION_WORDS:
            continue
        if intent == "add" and qty is None and re.fullmatch(r"\d+", w):
            qty = int(w)
            continue
        keep.append(w)
    return {"intent": intent, "query": " ".join(keep).strip(), "qty": qty}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def phone_for_links(phone: str, country_code: str = "90") -> str:
    """Telefonu uluslararası rakam dizisine çevirir (wa.me, t.me ve tel: bağlantıları için)."""
    p = (phone or "").strip()
    digits = re.sub(r"\D", "", p)
    if not digits:
        return ""
    if p.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return country_code + digits[1:]
    if len(digits) <= 10:
        return country_code + digits
    return digits


def _later_than(mtime):
    """Şimdiki zaman; yerel kayıt (ör. saati ileri bir cihazdan gelmiş) daha yeniyse ondan 1 ms sonrası."""
    now = now_utc()
    if not mtime or mtime < now:
        return now
    from datetime import timedelta
    try:
        d = datetime.strptime(mtime.rstrip("Z")[:23], "%Y-%m-%dT%H:%M:%S.%f") + timedelta(milliseconds=1)
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"
    except ValueError:
        return mtime + "1"


def _record_name(table, rec):
    return str(rec.get("name") or "")[:120]


_VOLATILE = {"mtime", "synced_at", "updated_at"}


def _same_record(a, b):
    """İki kayıt (eşitleme biçimi) zaman damgaları dışında aynı mı?"""
    keys = (set(a) | set(b)) - _VOLATILE
    return all(a.get(k) == b.get(k) for k in keys if k in a and k in b)


def now_utc() -> str:
    """Eşitleme için UTC zaman damgası (milisaniyeli ISO)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_uid() -> str:
    return uuid.uuid4().hex


def default_uid(table, tr_name) -> str:
    """Hazır yer/kategoriler her cihazda aynı kimliği alır; böylece eşitlemede çift olmaz."""
    slug = norm(tr_name)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"def-{'loc' if table == 'locations' else 'cat'}-{slug}"


# Sıralama anahtarları: "<alan>_asc" / "<alan>_desc"; eski adlar da geçerli.
SORT_ALIASES = {"newest": "created_desc", "oldest": "created_asc", "category": "category_asc",
                "location": "location_asc"}


def sort_records(rows, sort, fields, empty=None):
    """Kayıtları alana göre sıralar; boş değerler her iki yönde de en sonda kalır, eşitlikte ada göre."""
    sort = SORT_ALIASES.get(sort, sort or "created_desc")
    field, _, direction = sort.rpartition("_")
    if field not in fields:
        field, direction = ("created", "desc") if "created" in fields else ("name", "asc")
    keyf = fields[field]
    is_empty = (empty or {}).get(field, lambda d: False)
    name = fields.get("name", lambda d: "")
    full = [d for d in rows if not is_empty(d)]
    blank = [d for d in rows if is_empty(d)]
    full.sort(key=name)
    full.sort(key=keyf, reverse=(direction == "desc"))
    blank.sort(key=name)
    return full + blank


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.photos_dir = self.data_dir / "fotograflar"
        self.thumbs_dir = self.photos_dir / "kucuk"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "organizer.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate_columns()
        self.conn.executescript(SCHEMA)
        self._seed()
        self._fill_uids()
        self._mark_auto_prices()

    # ------------------------------------------------------------------ kurulum / göç
    def _migrate_columns(self):
        """v1 veritabanlarına eşitleme sütunlarını ekler."""
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in SYNC_TABLES:
            if table not in tables:
                continue
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in (("uid", "uid TEXT"),
                             ("mtime", f"mtime TEXT NOT NULL DEFAULT '{SEED_MTIME}'"),
                             ("deleted", "deleted INTEGER NOT NULL DEFAULT 0"),
                             ("dirty", "dirty INTEGER NOT NULL DEFAULT 1")):
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            if table == "items":
                for col in SHOP_TEXT:
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
                for col in SHOP_FLAGS + ("price_auto",):
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE items ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            extra = ITEM_EXTRA if table == "items" else CONTACT_EXTRA if table == "contacts" else {}
            for col, (ddl, _d, _k) in extra.items():
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        self.conn.commit()

    def _fill_uids(self):
        from .i18n import DEFAULT_NAMES
        reverse = {}
        for tr_name, (en, ar) in DEFAULT_NAMES.items():
            for n in (tr_name, en, ar):
                reverse.setdefault(n, tr_name)
        with self.conn:
            for table in SYNC_TABLES:
                used = {r[0] for r in self.conn.execute(f"SELECT uid FROM {table} WHERE uid IS NOT NULL")}
                for r in self.conn.execute(f"SELECT id, name FROM {table} WHERE uid IS NULL").fetchall():
                    uid = None
                    if table in TREE_TABLES and r["name"] in reverse:
                        cand = default_uid(table, reverse[r["name"]])
                        if cand not in used:
                            uid = cand
                    uid = uid or new_uid()
                    used.add(uid)
                    self.conn.execute(f"UPDATE {table} SET uid=? WHERE id=?", (uid, r["id"]))
            for table in SYNC_TABLES:
                self.conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_uid ON {table}(uid)")

    def _backup_candidates(self):
        import sys
        roots = [self.data_dir]
        try:
            exe = Path(sys.argv[0]).resolve()
            roots += list(exe.parents)[:5]
        except Exception:
            pass
        for base in (Path("C:/Claude Programlarım"), Path.home() / "Claude Programlarım"):
            if base.is_dir():
                roots.append(base)
                roots += [p for p in base.iterdir() if p.is_dir()]
        seen = set()
        for r in roots:
            for p in (r / "_gelistirme" / AUTO_PRICE_BACKUP, r / AUTO_PRICE_BACKUP):
                if p not in seen:
                    seen.add(p)
                    if p.is_file():
                        yield p

    def _mark_auto_prices(self):
        """Bir kerelik: 2026-11-18'de toplu girilen tahmini fiyatları "otomatik" olarak işaretler.

        Yedek veritabanı bulunursa: o gün fiyatı boş olup şimdi fiyatı olan ve o günden beri
        değiştirilmemiş eşyalar. Yedek yoksa: mtime'ı toplu işlem aralığında kalan fiyatlı eşyalar.
        İşaretlenen kayıt eşitlenir (telefon da görsün)."""
        if self.get_setting("price_auto_v1"):
            return
        start, end = AUTO_PRICE_BATCH
        rows = self.conn.execute("SELECT id, uid, mtime FROM items WHERE deleted=0 AND price IS NOT NULL "
                                 "AND price_auto=0").fetchall()
        marked = []
        backup = next(self._backup_candidates(), None)
        if backup is not None:
            try:
                b = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
                empty = {r[0] for r in b.execute("SELECT uid FROM items WHERE price IS NULL AND uid IS NOT NULL")}
                b.close()
                marked = [r["id"] for r in rows if r["uid"] in empty and (r["mtime"] or "")[:16] <= end]
            except Exception:
                backup = None
        if backup is None:
            marked = [r["id"] for r in rows if start <= (r["mtime"] or "")[:16] <= end]
        with self.conn:
            ts = now_utc()
            self.conn.executemany("UPDATE items SET price_auto=1, mtime=?, dirty=1 WHERE id=?",
                                  [(ts, i) for i in marked])
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('price_auto_v1', ?)",
                              (f"{len(marked)} {'yedek' if backup else 'zaman'}",))

    def _seed(self):
        if self.get_setting("seeded"):
            return
        from .i18n import LANG, default_name
        with self.conn:
            for table, data in (("locations", DEFAULT_LOCATIONS), ("categories", DEFAULT_CATEGORIES)):
                for i, (name, children) in enumerate(data):
                    cur = self.conn.execute(
                        f"INSERT INTO {table}(name, parent_id, sort, uid, mtime, dirty) VALUES (?, NULL, ?, ?, ?, 1)",
                        (default_name(name, LANG), i, default_uid(table, name), SEED_MTIME))
                    for j, child in enumerate(children):
                        self.conn.execute(
                            f"INSERT INTO {table}(name, parent_id, sort, uid, mtime, dirty) VALUES (?, ?, ?, ?, ?, 1)",
                            (default_name(child, LANG), cur.lastrowid, j, default_uid(table, child), SEED_MTIME))
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('seeded', '1')")

    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self.conn:
            if value is None:
                self.conn.execute("DELETE FROM settings WHERE key=?", (key,))
            else:
                self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))

    # ------------------------------------------------------------------ ağaçlar
    @staticmethod
    def _check(table):
        if table not in TREE_TABLES:
            raise ValueError(table)

    def tree_rows(self, table):
        self._check(table)
        return [dict(r) for r in self.conn.execute(
            f"SELECT id, name, parent_id, sort FROM {table} WHERE deleted=0 ORDER BY sort, name")]

    def tree_ordered(self, table):
        """Ağacı derinlik öncelikli sırayla döndürür: [(id, ad, derinlik, tam_yol)]."""
        rows = self.tree_rows(table)
        ids = {r["id"] for r in rows}
        children = {}
        for r in rows:
            parent = r["parent_id"] if r["parent_id"] in ids else None
            children.setdefault(parent, []).append(r)
        out = []

        def walk(parent, depth, prefix):
            for r in children.get(parent, []):
                path = f"{prefix} › {r['name']}" if prefix else r["name"]
                out.append((r["id"], r["name"], depth, path))
                walk(r["id"], depth + 1, path)

        walk(None, 0, "")
        return out

    def tree_paths(self, table):
        return {nid: path for nid, _, _, path in self.tree_ordered(table)}

    def descendants(self, table, node_id):
        rows = self.tree_rows(table)
        children = {}
        for r in rows:
            children.setdefault(r["parent_id"], []).append(r["id"])
        result, stack = set(), [node_id]
        while stack:
            n = stack.pop()
            if n in result:
                continue
            result.add(n)
            stack.extend(children.get(n, []))
        return result

    def add_node(self, table, name, parent_id=None):
        self._check(table)
        with self.conn:
            sort = self.conn.execute(
                f"SELECT COALESCE(MAX(sort), -1) + 1 FROM {table} WHERE parent_id IS ? AND deleted=0",
                (parent_id,)).fetchone()[0]
            cur = self.conn.execute(
                f"INSERT INTO {table}(name, parent_id, sort, uid, mtime, dirty) VALUES (?, ?, ?, ?, ?, 1)",
                (name.strip(), parent_id, sort, new_uid(), now_utc()))
        return cur.lastrowid

    def rename_node(self, table, node_id, name):
        self._check(table)
        with self.conn:
            self.conn.execute(f"UPDATE {table} SET name=?, mtime=?, dirty=1 WHERE id=?",
                              (name.strip(), now_utc(), node_id))

    def set_structure(self, table, entries):
        """entries: [(id, parent_id, sort)] — sürükle-bırak sonrası ağacı kaydeder."""
        self._check(table)
        ts = now_utc()
        with self.conn:
            for i, p, s in entries:
                self.conn.execute(
                    f"UPDATE {table} SET parent_id=?, sort=?, mtime=?, dirty=1 "
                    f"WHERE id=? AND (parent_id IS NOT ? OR sort<>?)", (p, s, ts, i, p, s))

    def move_node(self, table, node_id, delta):
        """Düğümü kardeşleri arasında yukarı (-1) ya da aşağı (+1) taşır."""
        self._check(table)
        row = self.conn.execute(f"SELECT parent_id FROM {table} WHERE id=?", (node_id,)).fetchone()
        if not row:
            return
        sibs = [r["id"] for r in self.tree_rows(table) if r["parent_id"] == row["parent_id"]]
        i = sibs.index(node_id)
        j = i + delta
        if 0 <= j < len(sibs):
            sibs[i], sibs[j] = sibs[j], sibs[i]
            self.set_structure(table, [(nid, row["parent_id"], k) for k, nid in enumerate(sibs)])

    def items_under(self, table, node_id):
        col = "location_id" if table == "locations" else "category_id"
        ids = self.descendants(table, node_id)
        marks = ",".join("?" * len(ids))
        return self.conn.execute(
            f"SELECT COUNT(*) FROM items WHERE deleted=0 AND trashed_at='' AND {col} IN ({marks})",
            tuple(ids)).fetchone()[0]

    def delete_node(self, table, node_id):
        """Düğümü alt düğümleriyle siler; içindeki eşyalar bir üst düğüme taşınır."""
        self._check(table)
        col = "location_id" if table == "locations" else "category_id"
        row = self.conn.execute(f"SELECT parent_id FROM {table} WHERE id=?", (node_id,)).fetchone()
        if not row:
            return
        ids = self.descendants(table, node_id)
        marks = ",".join("?" * len(ids))
        ts = now_utc()
        with self.conn:
            self.conn.execute(
                f"UPDATE items SET {col}=?, mtime=?, dirty=1 WHERE deleted=0 AND {col} IN ({marks})",
                (row["parent_id"], ts, *ids))
            self.conn.execute(f"UPDATE {table} SET deleted=1, mtime=?, dirty=1 WHERE id IN ({marks})",
                              (ts, *ids))

    def item_counts(self, table):
        col = "location_id" if table == "locations" else "category_id"
        return {r[0]: r[1] for r in self.conn.execute(
            f"SELECT {col}, COUNT(*) FROM items WHERE deleted=0 AND trashed_at='' GROUP BY {col}")}

    def translate_defaults(self, old_lang, new_lang):
        """Hazır gelen ve kullanıcının değiştirmediği yer/kategori adlarını yeni dile çevirir.
        Yalnızca bu cihazdaki görünümü değiştirir; buluta değişiklik olarak gönderilmez."""
        from .i18n import DEFAULT_NAMES, default_name
        with self.conn:
            for table in TREE_TABLES:
                for r in self.tree_rows(table):
                    for tr_name in DEFAULT_NAMES:
                        if r["name"] == default_name(tr_name, old_lang):
                            self.conn.execute(f"UPDATE {table} SET name=? WHERE id=?",
                                              (default_name(tr_name, new_lang), r["id"]))
                            break

    # ------------------------------------------------------------------ değişiklik geçmişi (2.3.0)
    def device_name(self):
        import platform
        return (self.get_setting("device_name") or "").strip() or platform.node() or "PC"

    def _uid_paths(self, table):
        paths = self.tree_paths(table)
        return {uid: paths.get(i, "") for uid, i in self._id_map(table).items()}

    def _state(self, ids):
        cats, locs = self._uid_paths("categories"), self._uid_paths("locations")
        out = {}
        for i in ids:
            r = self._export_one("items", i)
            if r is not None:
                r["category"], r["location"] = cats.get(r["category"], ""), locs.get(r["location"], "")
                out[i] = r
        return out

    @contextmanager
    def track(self, ids, action=""):
        """with db.track([id], "eylem"): ... — bloktan önceki ve sonraki hal karşılaştırılıp geçmişe yazılır."""
        before = self._state([i for i in ids if i])
        yield
        self._log(before, action)

    def _log(self, before, action=""):
        if not before:
            return
        after = self._state(list(before))
        ts, dev, who = now_utc(), self.device_name(), self.get_setting("fb_email", "") or ""
        with self.conn:
            for i, old in before.items():
                new = after.get(i)
                if new is None:
                    continue
                ch = [[f, _short(old.get(f)), _short(new.get(f))] for f in TRACKED
                      if _short(old.get(f)) != _short(new.get(f))]
                if not ch and not action:
                    continue
                entry = {"t": ts, "d": dev, "c": ch}
                if who:
                    entry["u"] = who
                if action:
                    entry["a"] = action
                log = merge_changelog(new.get("changelog"), [entry])
                self.conn.execute("UPDATE items SET changelog=? WHERE id=?", (json.dumps(log, ensure_ascii=False), i))

    def _log_created(self, item_id):
        e = {"t": now_utc(), "d": self.device_name(), "c": [], "a": "eklendi"}
        who = self.get_setting("fb_email", "") or ""
        if who:
            e["u"] = who
        row = self.conn.execute("SELECT changelog FROM items WHERE id=?", (item_id,)).fetchone()
        if row is not None:
            with self.conn:
                self.conn.execute("UPDATE items SET changelog=? WHERE id=?", (json.dumps(
                    merge_changelog(_extra_from_db("j", row["changelog"]), [e]), ensure_ascii=False), item_id))

    def changelog(self, item_id):
        row = self.conn.execute("SELECT changelog FROM items WHERE id=?", (item_id,)).fetchone()
        return list(reversed(_extra_from_db("j", row["changelog"]))) if row else []

    # ------------------------------------------------------------------ eşyalar
    def count_items(self):
        return self.conn.execute("SELECT COUNT(*) FROM items WHERE deleted=0 AND trashed_at=''").fetchone()[0]

    @staticmethod
    def _decode_item(d):
        for f, (_ddl, _dv, kind) in ITEM_EXTRA.items():
            d[f] = _extra_from_db(kind, d.get(f))
        return d

    def list_items(self, search="", category_ids=None, location_ids=None, sort="newest", trashed=False):
        rows = self.conn.execute(f"""
            SELECT i.*,
                   (SELECT filename FROM item_photos p WHERE p.item_id=i.id AND p.filename NOT LIKE '{RECEIPT_PREFIX}%'
                     ORDER BY p.sort, p.id LIMIT 1) AS photo,
                   (SELECT COUNT(*) FROM item_photos p WHERE p.item_id=i.id
                     AND p.filename NOT LIKE '{RECEIPT_PREFIX}%') AS photo_count,
                   (SELECT COUNT(*) FROM item_photos p WHERE p.item_id=i.id
                     AND p.filename LIKE '{RECEIPT_PREFIX}%') AS receipt_count
            FROM items i WHERE i.deleted=0 AND {"i.trashed_at<>''" if trashed else "i.trashed_at=''"}""").fetchall()
        cat_paths = self.tree_paths("categories")
        loc_paths = self.tree_paths("locations")
        terms = [w for w in norm(search).split() if w not in QUESTION_WORDS] if search else []
        result = []
        for r in rows:
            cat = r["category_id"] if r["category_id"] in cat_paths else None
            loc = r["location_id"] if r["location_id"] in loc_paths else None
            if category_ids is not None and cat not in category_ids:
                continue
            if location_ids is not None and loc not in location_ids:
                continue
            d = self._decode_item(dict(r))
            d["category_id"], d["location_id"] = cat, loc
            d["category_path"] = cat_paths.get(cat, "")
            d["location_path"] = loc_paths.get(loc, "")
            if terms:
                hay = norm(" ".join((d["name"], d["notes"], d["category_path"], d["location_path"],
                                     d["shop_name"], d["shop_place"], d["shop_phone"], d["loan_to"],
                                     re.sub(r"\D", "", d["shop_phone"]))))
                if not all(term_in(t, hay) for t in terms):
                    continue
            result.append(d)

        result = sort_records(result, sort, {
            "created": lambda d: d["created_at"], "name": lambda d: norm(d["name"]),
            "qty": lambda d: d["quantity"], "price": lambda d: (d["currency"], d["price"]),
            "category": lambda d: norm(d["category_path"]), "location": lambda d: norm(d["location_path"]),
            "shop": lambda d: norm(d["shop_name"] or d["shop_place"] or d["shop_phone"]),
            "place": lambda d: norm(d["shop_place"]),
            "trashed": lambda d: d["trashed_at"],
        }, empty={"price": lambda d: d["price"] is None, "category": lambda d: not d["category_path"],
                  "location": lambda d: not d["location_path"],
                  "shop": lambda d: not (d["shop_name"] or d["shop_place"] or d["shop_phone"]),
                  "place": lambda d: not (d["shop_place"] or "").strip()})
        return result

    def get_item(self, item_id):
        row = self.conn.execute("SELECT * FROM items WHERE id=? AND deleted=0", (item_id,)).fetchone()
        if not row:
            return None
        d = self._decode_item(dict(row))
        allp = self.item_photos(item_id)
        d["photos"] = [f for f in allp if not is_receipt(f)]
        d["receipts"] = [f for f in allp if is_receipt(f)]
        d["category_path"] = self.tree_paths("categories").get(d["category_id"], "")
        d["location_path"] = self.tree_paths("locations").get(d["location_id"], "")
        return d

    def item_photos(self, item_id):
        return [r["filename"] for r in self.conn.execute(
            "SELECT filename FROM item_photos WHERE item_id=? ORDER BY sort, id", (item_id,))]

    def contact_photos(self, cid):
        return [r["filename"] for r in self.conn.execute(
            "SELECT filename FROM contact_photos WHERE contact_id=? ORDER BY sort, id", (cid,))]

    # fotoğraf tablosu: (tablo, sahip sütunu, okuyucu)
    def _photo_table(self, owner):
        return ("item_photos", "item_id", self.item_photos) if owner == "items" else \
               ("contact_photos", "contact_id", self.contact_photos)

    def save_item(self, data, photos=None, item_id=None):
        """Eşyayı kaydeder; değişiklik geçmişine yazar (2.3.0)."""
        if item_id is None:
            new_id = self._save_item(data, photos, None)
            self._log_created(new_id)
            return new_id
        with self.track([item_id]):
            return self._save_item(data, photos, item_id)

    def _save_item(self, data, photos=None, item_id=None):
        """data: name, quantity, location_id, category_id, price, currency, notes, created_at,
        shop_name, shop_place, shop_phone, shop_whatsapp, shop_telegram.
        photos: [("existing", dosya_adı) | ("new", kaynak_yol)] ya da None (dokunma)."""
        fields = ("name", "quantity", "location_id", "category_id", "price", "currency",
                  "notes", "created_at") + SHOP_FIELDS + ("price_auto",)
        values = [data.get(f) for f in fields]
        values[-1] = int(bool(data.get("price_auto")) and data.get("price") is not None)
        if "min_qty" in data:
            fields += ("min_qty",)
            values.append(_extra_to_db("i", data.get("min_qty")))
        for f in ("warranty_until", "expires_on"):     # 2.3.0
            if f in data:
                fields += (f,)
                values.append(norm_day(data.get(f)))
        for i, f in enumerate(fields):
            if f in SHOP_TEXT:
                values[i] = (values[i] or "").strip()
            elif f in SHOP_FLAGS:
                values[i] = int(bool(values[i]))
        with self.conn:
            if item_id is None:
                cur = self.conn.execute(
                    f"INSERT INTO items({', '.join(fields)}, updated_at, uid, mtime, dirty) "
                    f"VALUES ({', '.join('?' * len(fields))}, ?, ?, ?, 1)",
                    (*values, now_str(), new_uid(), now_utc()))
                item_id = cur.lastrowid
            else:
                self.conn.execute(
                    f"UPDATE items SET {', '.join(f + '=?' for f in fields)}, updated_at=?, mtime=?, dirty=1 "
                    f"WHERE id=?", (*values, now_str(), now_utc(), item_id))
        if photos is not None:
            self._set_photos(item_id, photos)
        return item_id

    def _set_photos(self, item_id, entries, owner="items"):
        old = set(self._photo_table(owner)[2](item_id))
        keep = []
        for kind, value in entries:
            if kind == "existing":
                keep.append(value)
            else:
                ext = Path(value).suffix.lower() or ".jpg"
                fname = f"{RECEIPT_PREFIX if kind == 'new_fis' else ''}{uuid.uuid4().hex}{ext}"
                shutil.copy2(value, self.photos_dir / fname)
                keep.append(fname)
        self._write_photo_rows(item_id, keep, owner)
        for f in old - set(keep):
            self._remove_photo_file(f)

    def _write_photo_rows(self, item_id, filenames, owner="items"):
        table, col, _ = self._photo_table(owner)
        with self.conn:
            self.conn.execute(f"DELETE FROM {table} WHERE {col}=?", (item_id,))
            self.conn.executemany(
                f"INSERT INTO {table}({col}, filename, sort) VALUES (?, ?, ?)",
                [(item_id, f, i) for i, f in enumerate(filenames)])

    def _remove_photo_file(self, fname):
        for p in (self.photos_dir / fname, self.thumbs_dir / (Path(fname).stem + ".png")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO photo_sync VALUES (?, 'delete')", (fname,))

    def update_items_field(self, item_ids, field, value):
        with self.track(item_ids, ""):
            return self._update_items_field(item_ids, field, value)

    def _update_items_field(self, item_ids, field, value):
        if field not in ("category_id", "location_id", "price_auto", "to_buy", "min_qty"):
            raise ValueError(field)
        with self.conn:
            self.conn.executemany(
                f"UPDATE items SET {field}=?, updated_at=?, mtime=?, dirty=1 WHERE id=?",
                [(value, now_str(), now_utc(), i) for i in item_ids])

    def change_quantity(self, item_id, delta):
        with self.track([item_id], ""):
            return self._change_quantity(item_id, delta)

    def _change_quantity(self, item_id, delta):
        with self.conn:
            self.conn.execute(
                "UPDATE items SET quantity=MAX(0, quantity+?), updated_at=?, mtime=?, dirty=1 WHERE id=?",
                (delta, now_str(), now_utc(), item_id))

    # ------------------------------------------------------------------ çöp kutusu (v.1.0.8)
    def trash_items(self, item_ids):
        with self.track(item_ids, "silindi"):
            return self._trash_items(item_ids)

    def _trash_items(self, item_ids):
        """Silinen eşyalar 30 gün çöp kutusunda kalır (fotoğraflarıyla birlikte), sonra kendiliğinden silinir."""
        ts = now_utc()
        with self.conn:
            self.conn.executemany("UPDATE items SET trashed_at=?, mtime=?, dirty=1 WHERE id=? AND deleted=0",
                                  [(ts, ts, i) for i in item_ids])

    delete_items = trash_items   # eski adla çağıranlar da çöp kutusuna atar

    def restore_items(self, item_ids):
        with self.track(item_ids, "geri_yuklendi"):
            return self._restore_items(item_ids)

    def _restore_items(self, item_ids):
        ts = now_utc()
        with self.conn:
            self.conn.executemany("UPDATE items SET trashed_at='', mtime=?, dirty=1 WHERE id=?",
                                  [(ts, i) for i in item_ids])

    def count_trash(self):
        return self.conn.execute("SELECT COUNT(*) FROM items WHERE deleted=0 AND trashed_at<>''").fetchone()[0]

    def purge_old_trash(self, days=TRASH_DAYS):
        """Çöp kutusunda süresi dolanları kalıcı olarak siler. Silinen sayıyı döndürür."""
        from datetime import timedelta
        limit = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM items WHERE deleted=0 AND trashed_at<>'' AND trashed_at<?", (limit,))]
        if ids:
            self.purge_items(ids)
        return len(ids)

    def purge_items(self, item_ids):
        """Çöp kutusundan temizleme: kayıt "silindi" işaretiyle yayılır, fotoğraflar silinir; kaydın kendisi
        (fotoğrafsız) Ayarlar → Arşiv'de kalır (2.2.0: hiçbir veri kalıcı silinmez)."""
        for item_id in item_ids:
            photos = self.item_photos(item_id)
            self._archive_local("items", item_id, "temizlendi")
            with self.conn:
                self.conn.execute("UPDATE items SET deleted=1, mtime=?, dirty=1 WHERE id=?",
                                  (now_utc(), item_id))
                self.conn.execute("DELETE FROM item_photos WHERE item_id=?", (item_id,))
            for f in photos:
                self._remove_photo_file(f)

    # ------------------------------------------------------------------ ödünç (v.1.0.8)
    def lend_item(self, item_id, to, phone="", date="", due=""):
        with self.track([item_id], ""):
            return self._lend_item(item_id, to, phone, date, due)

    def _lend_item(self, item_id, to, phone="", date="", due=""):
        with self.conn:
            self.conn.execute("UPDATE items SET loan_to=?, loan_phone=?, loan_date=?, loan_due=?, updated_at=?, "
                              "mtime=?, dirty=1 WHERE id=?",
                              ((to or "").strip(), (phone or "").strip(), date or today_str(), due or "",
                               now_str(), now_utc(), item_id))

    def return_item(self, item_id):
        with self.track([item_id], ""):
            return self._return_item(item_id)

    def _return_item(self, item_id):
        """Ödünç verilen eşya geri geldi: kayıt geçmişe eklenir."""
        import json
        row = self.conn.execute("SELECT loan_to, loan_phone, loan_date, loan_due, loan_history FROM items WHERE id=?",
                                (item_id,)).fetchone()
        if not row or not row["loan_to"]:
            return
        hist = _extra_from_db("j", row["loan_history"])
        hist.append({"to": row["loan_to"], "phone": row["loan_phone"], "date": row["loan_date"],
                     "due": row["loan_due"], "returned": today_str()})
        with self.conn:
            self.conn.execute("UPDATE items SET loan_to='', loan_phone='', loan_date='', loan_due='', loan_history=?, "
                              "updated_at=?, mtime=?, dirty=1 WHERE id=?",
                              (json.dumps(hist[-50:], ensure_ascii=False), now_str(), now_utc(), item_id))

    def loan_counts(self):
        """(ödünçteki eşya sayısı, gecikenlerin sayısı)"""
        today = today_str()
        rows = self.conn.execute("SELECT loan_due FROM items WHERE deleted=0 AND trashed_at='' AND loan_to<>''").fetchall()
        return len(rows), sum(1 for r in rows if r[0] and r[0] < today)

    # ------------------------------------------------------------------ stok / alışveriş listesi (v.1.0.8)
    @staticmethod
    def is_low(d):
        return int(d.get("min_qty") or 0) > 0 and int(d.get("quantity") or 0) < int(d["min_qty"])

    def shopping_list(self):
        """Alışveriş listesi: adedi "en az" sınırının altına düşenler + elle listeye eklenenler."""
        items = self.list_items(sort="name_asc")
        return [d for d in items if d["to_buy"] or self.is_low(d)]

    def bought(self, item_id, qty):
        with self.track([item_id], ""):
            return self._bought(item_id, qty)

    def _bought(self, item_id, qty):
        """Alındı: adet artar, elle eklenmişse listeden çıkar."""
        with self.conn:
            self.conn.execute("UPDATE items SET quantity=quantity+?, to_buy=0, updated_at=?, mtime=?, dirty=1 WHERE id=?",
                              (max(0, int(qty)), now_str(), now_utc(), item_id))

    # ------------------------------------------------------------------ usta iş geçmişi (v.1.0.8)
    def contact_jobs(self, cid):
        row = self.conn.execute("SELECT jobs FROM contacts WHERE id=?", (cid,)).fetchone()
        return _extra_from_db("j", row["jobs"]) if row else []

    def save_jobs(self, cid, jobs):
        import json
        with self.conn:
            self.conn.execute("UPDATE contacts SET jobs=?, mtime=?, dirty=1 WHERE id=?",
                              (json.dumps(list(jobs), ensure_ascii=False), now_utc(), cid))

    @staticmethod
    def jobs_total(jobs):
        out = {}
        for j in jobs or []:
            if j.get("cost") not in (None, ""):
                try:
                    out[j.get("currency") or "USD"] = out.get(j.get("currency") or "USD", 0) + float(j["cost"])
                except (TypeError, ValueError):
                    pass
        return out

    # ------------------------------------------------------------------ geri al (v.1.0.8)
    def snapshot(self, item_ids):
        """Değişiklikten önceki hali: geri al için. [{sütunlar..., "_photos": [...]}]"""
        out = []
        for i in item_ids:
            row = self.conn.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
            if row:
                d = dict(row)
                d["_photos"] = self.item_photos(i)
                out.append(d)
        return out

    def restore_snapshot(self, snap):
        with self.track([d['id'] for d in snap], "geri_alindi"):
            return self._restore_snapshot(snap)

    def _restore_snapshot(self, snap):
        """Kaydedilen hali geri yükler; değişiklik yeni bir düzenleme olarak eşitlenir."""
        ts = now_utc()
        skip = {"id", "uid", "mtime", "dirty", "_photos", "changelog"}
        with self.conn:
            for d in snap:
                cols = [c for c in d if c not in skip]
                self.conn.execute(f"UPDATE items SET {', '.join(c + '=?' for c in cols)}, mtime=?, dirty=1 WHERE id=?",
                                  (*[d[c] for c in cols], ts, d["id"]))
        for d in snap:
            photos = [f for f in d["_photos"] if (self.photos_dir / f).exists()]
            for f in photos:
                self.conn.execute("DELETE FROM photo_sync WHERE filename=? AND state='delete'", (f,))
            self._write_photo_rows(d["id"], photos)
        self.conn.commit()

    def totals_by_currency(self, items):
        totals = {}
        for d in items:
            if d["price"] is not None:
                totals[d["currency"]] = totals.get(d["currency"], 0) + d["price"]
        return totals

    # ------------------------------------------------------------------ ustalar
    def list_contacts(self, search="", kind=None, sort="name_asc"):
        rows = [dict(r) for r in self.conn.execute("""
            SELECT c.*,
                   (SELECT filename FROM contact_photos p WHERE p.contact_id=c.id
                     ORDER BY p.sort, p.id LIMIT 1) AS photo,
                   (SELECT COUNT(*) FROM contact_photos p WHERE p.contact_id=c.id) AS photo_count
            FROM contacts c WHERE c.deleted=0""")]
        for d in rows:
            d["jobs"] = _extra_from_db("j", d.get("jobs"))
        terms = norm(search).split()
        out = []
        for d in rows:
            if kind and d["kind"] != kind:
                continue
            if terms:
                digits = re.sub(r"\D", "", d["phone"])
                jobs = " ".join(str(j.get("work") or "") for j in d["jobs"])
                hay = norm(" ".join((d["name"], d["profession"], d["place"], d["phone"], digits, d["notes"], jobs)))
                if not all(t in hay for t in terms):
                    continue
            out.append(d)
        return sort_records(out, sort, {
            "name": lambda d: norm(d["name"]), "kind": lambda d: (d["kind"], norm(d["name"])),
            "prof": lambda d: norm(d["profession"]), "place": lambda d: norm(d["place"]),
            "phone": lambda d: re.sub(r"\D", "", d["phone"]), "notes": lambda d: norm(d["notes"]),
            "created": lambda d: d["created_at"],
        }, empty={k: (lambda f: lambda d: not d[f])(f) for k, f in
                  (("prof", "profession"), ("place", "place"), ("phone", "phone"), ("notes", "notes"))})

    def get_contact(self, cid):
        row = self.conn.execute("SELECT * FROM contacts WHERE id=? AND deleted=0", (cid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["photos"] = self.contact_photos(cid)
        d["jobs"] = _extra_from_db("j", d.get("jobs"))
        return d

    def save_contact(self, data, cid=None, photos=None):
        """photos: [("existing", dosya_adı) | ("new", kaynak_yol)] ya da None (dokunma)."""
        cid = self._save_contact_row(data, cid)
        if photos is not None:
            self._set_photos(cid, photos, owner="contacts")
        return cid

    def _save_contact_row(self, data, cid=None):
        fields = ("kind", "name", "profession", "place", "phone",
                  "has_whatsapp", "has_telegram", "has_call", "notes")
        values = [data.get(f) for f in fields]
        with self.conn:
            if cid is None:
                cur = self.conn.execute(
                    f"INSERT INTO contacts({', '.join(fields)}, created_at, uid, mtime, dirty) "
                    f"VALUES ({', '.join('?' * len(fields))}, ?, ?, ?, 1)",
                    (*values, now_str(), new_uid(), now_utc()))
                return cur.lastrowid
            self.conn.execute(
                f"UPDATE contacts SET {', '.join(f + '=?' for f in fields)}, mtime=?, dirty=1 WHERE id=?",
                (*values, now_utc(), cid))
            return cid

    def delete_contacts(self, ids):
        for cid in ids:
            photos = self.contact_photos(cid)
            self._archive_local("contacts", cid, "temizlendi")
            with self.conn:
                self.conn.execute("UPDATE contacts SET deleted=1, mtime=?, dirty=1 WHERE id=?", (now_utc(), cid))
                self.conn.execute("DELETE FROM contact_photos WHERE contact_id=?", (cid,))
            for f in photos:
                self._remove_photo_file(f)

    def known_shops(self):
        """Daha önce girilmiş dükkanlar (eşyalardan ve Ustalar & Dükkanlar listesinden): ad → bilgiler.
        Eşya formunda dükkan adı yazılınca yeri ve numarası kendiliğinden doldurulur."""
        out = {}
        for r in self.conn.execute("SELECT name, place, phone, has_whatsapp, has_telegram FROM contacts "
                                   "WHERE deleted=0 AND kind='dukkan' AND name<>''"):
            out[r["name"]] = {"shop_place": r["place"], "shop_phone": r["phone"],
                              "shop_whatsapp": bool(r["has_whatsapp"]), "shop_telegram": bool(r["has_telegram"])}
        for r in self.conn.execute("SELECT shop_name, shop_place, shop_phone, shop_whatsapp, shop_telegram FROM items "
                                   "WHERE deleted=0 AND shop_name<>'' ORDER BY mtime"):
            out[r["shop_name"]] = {"shop_place": r["shop_place"], "shop_phone": r["shop_phone"],
                                   "shop_whatsapp": bool(r["shop_whatsapp"]), "shop_telegram": bool(r["shop_telegram"])}
        return out

    def professions(self):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT profession FROM contacts WHERE profession<>'' AND deleted=0 ORDER BY profession")]

    # ------------------------------------------------------------------ eşitleme
    def _uid_map(self, table):
        return {r["id"]: r["uid"] for r in self.conn.execute(f"SELECT id, uid FROM {table}")}

    def _id_map(self, table):
        return {r["uid"]: r["id"] for r in self.conn.execute(f"SELECT id, uid FROM {table}")}

    def dirty_records(self):
        """Buluta gönderilecek kayıtlar: {tablo: [ortak biçimde kayıt]}."""
        return self._records("dirty=1")

    def all_records(self):
        """Bütün kayıtlar (silinmişler dahil) — yerel ağ eşitlemesi için."""
        return self._records("1=1")

    def _records(self, where):
        out = {}
        loc_uid, cat_uid = self._uid_map("locations"), self._uid_map("categories")
        for table in TREE_TABLES:
            uids = loc_uid if table == "locations" else cat_uid
            out[table] = [{"uid": r["uid"], "name": r["name"], "parent": uids.get(r["parent_id"], ""),
                           "sort": r["sort"], "mtime": r["mtime"], "deleted": bool(r["deleted"])}
                          for r in self.conn.execute(f"SELECT * FROM {table} WHERE {where}")]
        out["items"] = []
        for r in self.conn.execute(f"SELECT * FROM items WHERE {where}").fetchall():
            out["items"].append({
                "uid": r["uid"], "name": r["name"], "quantity": r["quantity"],
                "location": loc_uid.get(r["location_id"], ""), "category": cat_uid.get(r["category_id"], ""),
                "price": r["price"], "currency": r["currency"], "notes": r["notes"],
                "created_at": r["created_at"], "photos": [] if r["deleted"] else self.item_photos(r["id"]),
                "shop_name": r["shop_name"], "shop_place": r["shop_place"], "shop_phone": r["shop_phone"],
                "shop_whatsapp": bool(r["shop_whatsapp"]), "shop_telegram": bool(r["shop_telegram"]),
                "price_auto": bool(r["price_auto"]),
                **{f: _extra_from_db(k, r[f]) for f, (_d, _v, k) in ITEM_EXTRA.items()},
                "mtime": r["mtime"], "deleted": bool(r["deleted"])})
        out["contacts"] = [{
            "uid": r["uid"], "kind": r["kind"], "name": r["name"], "profession": r["profession"],
            "place": r["place"], "phone": r["phone"], "has_whatsapp": bool(r["has_whatsapp"]),
            "has_telegram": bool(r["has_telegram"]), "has_call": bool(r["has_call"]), "notes": r["notes"],
            "created_at": r["created_at"], "photos": [] if r["deleted"] else self.contact_photos(r["id"]),
            **{f: _extra_from_db(k, r[f]) for f, (_d, _v, k) in CONTACT_EXTRA.items()},
            "mtime": r["mtime"], "deleted": bool(r["deleted"])}
            for r in self.conn.execute(f"SELECT * FROM contacts WHERE {where}").fetchall()]
        return out

    def mark_clean(self, table, uid, mtime):
        with self.conn:
            self.conn.execute(f"UPDATE {table} SET dirty=0 WHERE uid=? AND mtime=?", (uid, mtime))

    def _merge_extras(self, table, rec, exists):
        """Yeni alanlar (v.1.0.8): kayıtta yoksa (eski sürümden geldi) yereldeki değer korunur."""
        extra = ITEM_EXTRA if table == "items" else CONTACT_EXTRA
        missing = [f for f in extra if f not in rec]
        if missing and exists:
            old = self.conn.execute(f"SELECT {', '.join(missing)} FROM {table} WHERE uid=?", (rec["uid"],)).fetchone()
            rec = {**rec, **{f: _extra_from_db(extra[f][2], old[f]) for f in missing}}
        if table == "items" and exists and "changelog" in rec and "changelog" not in missing:
            # 2.3.0: iki cihazın değişiklik geçmişi birleşir (biri ötekini silmez)
            old = self.conn.execute("SELECT changelog FROM items WHERE uid=?", (rec["uid"],)).fetchone()
            if old is not None:
                rec = {**rec, "changelog": merge_changelog(_extra_from_db("j", old["changelog"]), rec.get("changelog"))}
        return [(f, _extra_to_db(k, rec.get(f, dv))) for f, (_ddl, dv, k) in extra.items()]

    def _set_extras(self, table, uid, pairs):
        if pairs:
            self.conn.execute(f"UPDATE {table} SET {', '.join(f + '=?' for f, _ in pairs)} WHERE uid=?",
                              (*[v for _, v in pairs], uid))

    def apply_remote(self, table, records, keep_dirty=False):
        """Buluttan (ya da yerel ağdan) gelen kayıtları birleştirir (son değişiklik kazanır).
        keep_dirty: kabul edilen kayıt buluta da gönderilsin (yerel ağdan gelenler). Değişen kayıt sayısını döndürür."""
        changed = 0
        local = {r["uid"]: r for r in self.conn.execute(f"SELECT uid, mtime, id, deleted, dirty FROM {table}")}
        accepted = []
        for rec in records:
            cur = local.get(rec["uid"])
            if cur is not None and cur["mtime"] >= rec.get("mtime", ""):
                if table == "items" and cur["mtime"] == rec.get("mtime") and "price_auto" in rec:
                    # aynı sürüm: yalnızca otomatik fiyat işaretini (eski sürümün düşürdüğü alan) tamamla
                    self.conn.execute("UPDATE items SET price_auto=? WHERE uid=?",
                                      (int(bool(rec["price_auto"])), rec["uid"]))
                continue
            accepted.append(rec)
        if not accepted:
            self.conn.commit()
            return 0
        # 2.2.0 eşitleme kuralı (ortak çekirdek lan-sync-merge): uzak silme yerelde kaydı yok etmez — kaydın son hali
        # (fotoğraf dosyalarıyla) arşive alınır; gönderilmemiş yerel değişikliğin üstüne yazılırsa eski hal çakışma yedeğine.
        keep_photos = set()
        archive = []
        for rec in accepted:
            cur = local.get(rec["uid"])
            if cur is None or cur["deleted"]:
                continue
            if rec.get("deleted"):
                kind = "silindi"
            elif cur["dirty"]:
                kind = "cakisma"
            else:
                continue
            old = self._export_one(table, cur["id"])
            if old is None or (kind == "cakisma" and _same_record(old, rec)):
                continue
            keep_photos.update(old.get("photos") or [])
            archive.append((table, rec["uid"], kind, "esitleme", now_utc(), _record_name(table, old),
                            json.dumps(old, ensure_ascii=False)))
        if archive:
            self.conn.executemany("INSERT INTO arsiv(tablo, uid, tur, kaynak, zaman, ad, veri) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  archive)
        with self.conn:
            if table in TREE_TABLES:
                for rec in accepted:
                    vals = (rec.get("name", ""), int(rec.get("sort", 0)), rec["mtime"], int(bool(rec.get("deleted"))))
                    if rec["uid"] in local:
                        self.conn.execute(f"UPDATE {table} SET name=?, sort=?, mtime=?, deleted=?, dirty=0 "
                                          f"WHERE uid=?", (*vals, rec["uid"]))
                    else:
                        self.conn.execute(f"INSERT INTO {table}(name, sort, mtime, deleted, dirty, uid) "
                                          f"VALUES (?, ?, ?, ?, 0, ?)", (*vals, rec["uid"]))
                    changed += 1
                ids = self._id_map(table)
                for rec in accepted:
                    parent = ids.get(rec.get("parent") or "")
                    if parent == ids[rec["uid"]]:
                        parent = None
                    self.conn.execute(f"UPDATE {table} SET parent_id=? WHERE uid=?", (parent, rec["uid"]))
            elif table == "items":
                locs, cats = self._id_map("locations"), self._id_map("categories")
                for rec in accepted:
                    price = rec.get("price")
                    if "shop_name" not in rec and rec["uid"] in local:
                        # 1.4.0 öncesi bir cihazdan gelen kayıt: satın alma yeri bilgisi silinmesin
                        old = self.conn.execute("SELECT " + ", ".join(SHOP_FIELDS) + " FROM items WHERE uid=?",
                                                (rec["uid"],)).fetchone()
                        rec = {**rec, **dict(old)}
                    if "price_auto" not in rec and rec["uid"] in local:
                        # işareti bilmeyen eski sürümden gelen kayıt: fiyat aynıysa yereldeki işaret korunur
                        old = self.conn.execute("SELECT price, price_auto FROM items WHERE uid=?",
                                                (rec["uid"],)).fetchone()
                        same = old["price"] is not None and price is not None and abs(old["price"] - float(price)) < 1e-9
                        rec = {**rec, "price_auto": bool(old["price_auto"]) and same}
                    vals = (rec.get("name", ""), int(rec.get("quantity") or 0),
                            locs.get(rec.get("location") or ""), cats.get(rec.get("category") or ""),
                            None if price is None else float(price), rec.get("currency") or "TRY",
                            rec.get("notes", ""), rec.get("created_at") or now_str(),
                            rec["mtime"], int(bool(rec.get("deleted"))),
                            *[str(rec.get(f) or "") for f in SHOP_TEXT],
                            *[int(bool(rec.get(f))) for f in SHOP_FLAGS],
                            int(bool(rec.get("price_auto")) and price is not None))
                    extras = self._merge_extras("items", rec, rec["uid"] in local)
                    if rec["uid"] in local:
                        item_id = local[rec["uid"]]["id"]
                        self.conn.execute(
                            "UPDATE items SET name=?, quantity=?, location_id=?, category_id=?, price=?, currency=?, "
                            "notes=?, created_at=?, mtime=?, deleted=?, shop_name=?, shop_place=?, shop_phone=?, "
                            "shop_whatsapp=?, shop_telegram=?, price_auto=?, dirty=0 WHERE id=?", (*vals, item_id))
                    else:
                        item_id = self.conn.execute(
                            "INSERT INTO items(name, quantity, location_id, category_id, price, currency, notes, "
                            "created_at, mtime, deleted, shop_name, shop_place, shop_phone, shop_whatsapp, "
                            "shop_telegram, price_auto, dirty, uid, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                            (*vals, rec["uid"], now_str())).lastrowid
                    self._set_extras("items", rec["uid"], extras)
                    old = set(self.item_photos(item_id))
                    new = [] if rec.get("deleted") else list(rec.get("photos") or [])
                    self.conn.execute("DELETE FROM item_photos WHERE item_id=?", (item_id,))
                    self.conn.executemany("INSERT INTO item_photos(item_id, filename, sort) VALUES (?, ?, ?)",
                                          [(item_id, f, i) for i, f in enumerate(new)])
                    self._unlink_photos(old - set(new) - keep_photos)
                    changed += 1
            elif table == "contacts":
                for rec in accepted:
                    vals = (rec.get("kind") or "usta", rec.get("name", ""), rec.get("profession", ""),
                            rec.get("place", ""), rec.get("phone", ""), int(bool(rec.get("has_whatsapp"))),
                            int(bool(rec.get("has_telegram"))), int(bool(rec.get("has_call"))),
                            rec.get("notes", ""), rec.get("created_at") or now_str(),
                            rec["mtime"], int(bool(rec.get("deleted"))))
                    extras = self._merge_extras("contacts", rec, rec["uid"] in local)
                    if rec["uid"] in local:
                        cid = local[rec["uid"]]["id"]
                        self.conn.execute(
                            "UPDATE contacts SET kind=?, name=?, profession=?, place=?, phone=?, has_whatsapp=?, "
                            "has_telegram=?, has_call=?, notes=?, created_at=?, mtime=?, deleted=?, dirty=0 "
                            "WHERE uid=?", (*vals, rec["uid"]))
                    else:
                        cid = self.conn.execute(
                            "INSERT INTO contacts(kind, name, profession, place, phone, has_whatsapp, has_telegram, "
                            "has_call, notes, created_at, mtime, deleted, dirty, uid) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)", (*vals, rec["uid"])).lastrowid
                    self._set_extras("contacts", rec["uid"], extras)
                    # 4.0 sürümünden gelen kayıtlarda "photos" alanı yoktur; o zaman fotoğraflara dokunma
                    if "photos" in rec or rec.get("deleted"):
                        old = set(self.contact_photos(cid))
                        new = [] if rec.get("deleted") else list(rec.get("photos") or [])
                        self.conn.execute("DELETE FROM contact_photos WHERE contact_id=?", (cid,))
                        self.conn.executemany("INSERT INTO contact_photos(contact_id, filename, sort) VALUES (?, ?, ?)",
                                              [(cid, f, i) for i, f in enumerate(new)])
                        self._unlink_photos(old - set(new) - keep_photos)
                    changed += 1
            if keep_dirty:
                self.conn.executemany(f"UPDATE {table} SET dirty=1 WHERE uid=?", [(r["uid"],) for r in accepted])
        return changed

    def photo_names(self):
        """Bu cihazda dosyası bulunan fotoğraflar."""
        return {p.name for p in self.photos_dir.iterdir() if p.is_file()}

    _ALL_PHOTOS = ("SELECT p.filename, i.uid FROM item_photos p JOIN items i ON i.id=p.item_id WHERE i.deleted=0 "
                   "UNION ALL SELECT p.filename, c.uid FROM contact_photos p JOIN contacts c ON c.id=p.contact_id "
                   "WHERE c.deleted=0")

    def _unlink_photos(self, names):
        for f in names:
            for p in (self.photos_dir / f, self.thumbs_dir / (Path(f).stem + ".png")):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

    def photos_to_upload(self):
        """Buluta henüz yüklenmemiş, silinmemiş eşya ve usta/dükkan fotoğrafları: [(dosya, sahibin uid'si)]."""
        done = {r[0] for r in self.conn.execute("SELECT filename FROM photo_sync")}
        rows = self.conn.execute(self._ALL_PHOTOS)
        return [(r[0], r[1]) for r in rows if r[0] not in done and (self.photos_dir / r[0]).exists()]

    def photos_to_delete(self):
        return [r[0] for r in self.conn.execute("SELECT filename FROM photo_sync WHERE state='delete'")]

    def missing_photos(self):
        rows = self.conn.execute(self._ALL_PHOTOS)
        return [r[0] for r in rows if not (self.photos_dir / r[0]).exists()]

    def set_photo_state(self, fname, state):
        with self.conn:
            if state is None:
                self.conn.execute("DELETE FROM photo_sync WHERE filename=?", (fname,))
            else:
                self.conn.execute("INSERT OR REPLACE INTO photo_sync VALUES (?, ?)", (fname, state))

    def reset_sync_state(self):
        """Başka bir hesaba bağlanınca her şey yeniden gönderilsin."""
        with self.conn:
            for table in SYNC_TABLES:
                self.conn.execute(f"UPDATE {table} SET dirty=1")
            self.conn.execute("DELETE FROM photo_sync")
            self.conn.execute("DELETE FROM settings WHERE key LIKE 'sync_cursor_%'")

    # ------------------------------------------------------------------ arşiv (2.2.0)
    def dirty_count(self):
        """Buluta henüz gönderilmemiş kayıt sayısı (üst çubuktaki Eşitle rozeti)."""
        return sum(self.conn.execute(f"SELECT COUNT(*) FROM {t} WHERE dirty=1").fetchone()[0] for t in SYNC_TABLES)

    def _export_one(self, table, row_id):
        uid = self.conn.execute(f"SELECT uid FROM {table} WHERE id=?", (row_id,)).fetchone()
        if not uid:
            return None
        recs = self._records(f"id={int(row_id)}").get(table) or []
        return recs[0] if recs else None

    def _archive_local(self, table, row_id, kind):
        old = self._export_one(table, row_id)
        if old is None or old.get("deleted"):
            return
        old = dict(old, photos=[])          # fotoğraflar kullanıcının isteğiyle silinir
        with self.conn:
            self.conn.execute("INSERT INTO arsiv(tablo, uid, tur, kaynak, zaman, ad, veri) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (table, old["uid"], kind, "yerel", now_utc(), _record_name(table, old),
                               json.dumps(old, ensure_ascii=False)))

    def archive_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM arsiv WHERE geri_alindi=''").fetchone()[0]

    def archive_list(self, limit=50):
        return [{"id": r["id"], "table": r["tablo"], "uid": r["uid"], "kind": r["tur"], "source": r["kaynak"],
                 "at": r["zaman"], "name": r["ad"]}
                for r in self.conn.execute("SELECT * FROM arsiv WHERE geri_alindi='' ORDER BY id DESC LIMIT ?", (limit,))]

    def archive_restore(self, aid):
        """Arşivdeki kaydı geri getirir: yeni bir değişiklik olarak yazılır (diğer cihazlara da gider)."""
        r = self.conn.execute("SELECT * FROM arsiv WHERE id=?", (aid,)).fetchone()
        if r is None:
            raise ValueError("arsiv")
        rec = json.loads(r["veri"])
        rec["deleted"] = False
        cur = self.conn.execute(f"SELECT mtime FROM {r['tablo']} WHERE uid=?", (rec["uid"],)).fetchone()
        rec["mtime"] = _later_than(cur["mtime"] if cur else "")
        if r["tablo"] == "items":
            rec["trashed_at"] = ""
            rec["photos"] = [f for f in (rec.get("photos") or []) if (self.photos_dir / f).exists()]
        if r["tablo"] == "contacts":
            rec["photos"] = [f for f in (rec.get("photos") or []) if (self.photos_dir / f).exists()]
        self.apply_remote(r["tablo"], [rec], keep_dirty=True)
        with self.conn:
            self.conn.execute("UPDATE arsiv SET geri_alindi=? WHERE id=?", (now_utc(), aid))
            for f in rec.get("photos") or []:
                self.conn.execute("DELETE FROM photo_sync WHERE filename=? AND state='delete'", (f,))
        return rec["uid"]

    # ------------------------------------------------------------------ yedek
    def backup(self, target_zip: Path):
        """Veritabanını ve fotoğrafları tek bir .zip dosyasına yedekler."""
        target_zip = Path(target_zip)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Organizer"
            (root / "fotograflar").mkdir(parents=True)
            dest = sqlite3.connect(str(root / "organizer.db"))
            self.conn.backup(dest)
            dest.close()
            for f in self.photos_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, root / "fotograflar" / f.name)
            base = str(target_zip.with_suffix(""))
            shutil.make_archive(base, "zip", root)
        return Path(base + ".zip")
