import re
import shutil
import sqlite3
import tempfile
import uuid
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

_UPPER_TR = str.maketrans({"İ": "i", "I": "ı"})
_FOLD_TR = str.maketrans("ıçğöşüâîûأإآٱةى", "icgosuaiuااااهي")
_AR_MARKS = dict.fromkeys(range(0x064B, 0x0653))  # Arapça hareke işaretleri


def norm(text) -> str:
    """Harf farklarına duyarsız arama için metni sadeleştirir (Çivi -> civi, أ -> ا)."""
    return (text or "").translate(_UPPER_TR).lower().translate(_FOLD_TR).translate(_AR_MARKS).replace("ـ", "")


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
                for col in SHOP_FLAGS:
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE items ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
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
            f"SELECT COUNT(*) FROM items WHERE deleted=0 AND {col} IN ({marks})", tuple(ids)).fetchone()[0]

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
            f"SELECT {col}, COUNT(*) FROM items WHERE deleted=0 GROUP BY {col}")}

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

    # ------------------------------------------------------------------ eşyalar
    def count_items(self):
        return self.conn.execute("SELECT COUNT(*) FROM items WHERE deleted=0").fetchone()[0]

    def list_items(self, search="", category_ids=None, location_ids=None, sort="newest"):
        rows = self.conn.execute("""
            SELECT i.*,
                   (SELECT filename FROM item_photos p WHERE p.item_id=i.id
                     ORDER BY p.sort, p.id LIMIT 1) AS photo,
                   (SELECT COUNT(*) FROM item_photos p WHERE p.item_id=i.id) AS photo_count
            FROM items i WHERE i.deleted=0""").fetchall()
        cat_paths = self.tree_paths("categories")
        loc_paths = self.tree_paths("locations")
        terms = norm(search).split()
        result = []
        for r in rows:
            cat = r["category_id"] if r["category_id"] in cat_paths else None
            loc = r["location_id"] if r["location_id"] in loc_paths else None
            if category_ids is not None and cat not in category_ids:
                continue
            if location_ids is not None and loc not in location_ids:
                continue
            d = dict(r)
            d["category_id"], d["location_id"] = cat, loc
            d["category_path"] = cat_paths.get(cat, "")
            d["location_path"] = loc_paths.get(loc, "")
            if terms:
                hay = norm(" ".join((d["name"], d["notes"], d["category_path"], d["location_path"],
                                     d["shop_name"], d["shop_place"], d["shop_phone"],
                                     re.sub(r"\D", "", d["shop_phone"]))))
                if not all(t in hay for t in terms):
                    continue
            result.append(d)

        result = sort_records(result, sort, {
            "created": lambda d: d["created_at"], "name": lambda d: norm(d["name"]),
            "qty": lambda d: d["quantity"], "price": lambda d: (d["currency"], d["price"]),
            "category": lambda d: norm(d["category_path"]), "location": lambda d: norm(d["location_path"]),
            "shop": lambda d: norm(d["shop_name"] or d["shop_place"] or d["shop_phone"]),
        }, empty={"price": lambda d: d["price"] is None, "category": lambda d: not d["category_path"],
                  "location": lambda d: not d["location_path"],
                  "shop": lambda d: not (d["shop_name"] or d["shop_place"] or d["shop_phone"])})
        return result

    def get_item(self, item_id):
        row = self.conn.execute("SELECT * FROM items WHERE id=? AND deleted=0", (item_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["photos"] = self.item_photos(item_id)
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
        """data: name, quantity, location_id, category_id, price, currency, notes, created_at,
        shop_name, shop_place, shop_phone, shop_whatsapp, shop_telegram.
        photos: [("existing", dosya_adı) | ("new", kaynak_yol)] ya da None (dokunma)."""
        fields = ("name", "quantity", "location_id", "category_id", "price", "currency",
                  "notes", "created_at") + SHOP_FIELDS
        values = [data.get(f) for f in fields]
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
                fname = f"{uuid.uuid4().hex}{ext}"
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
        if field not in ("category_id", "location_id"):
            raise ValueError(field)
        with self.conn:
            self.conn.executemany(
                f"UPDATE items SET {field}=?, updated_at=?, mtime=?, dirty=1 WHERE id=?",
                [(value, now_str(), now_utc(), i) for i in item_ids])

    def change_quantity(self, item_id, delta):
        with self.conn:
            self.conn.execute(
                "UPDATE items SET quantity=MAX(0, quantity+?), updated_at=?, mtime=?, dirty=1 WHERE id=?",
                (delta, now_str(), now_utc(), item_id))

    def delete_items(self, item_ids):
        for item_id in item_ids:
            photos = self.item_photos(item_id)
            with self.conn:
                self.conn.execute("UPDATE items SET deleted=1, mtime=?, dirty=1 WHERE id=?",
                                  (now_utc(), item_id))
                self.conn.execute("DELETE FROM item_photos WHERE item_id=?", (item_id,))
            for f in photos:
                self._remove_photo_file(f)

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
        terms = norm(search).split()
        out = []
        for d in rows:
            if kind and d["kind"] != kind:
                continue
            if terms:
                digits = re.sub(r"\D", "", d["phone"])
                hay = norm(" ".join((d["name"], d["profession"], d["place"], d["phone"], digits, d["notes"])))
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
        out = {}
        loc_uid, cat_uid = self._uid_map("locations"), self._uid_map("categories")
        for table in TREE_TABLES:
            uids = loc_uid if table == "locations" else cat_uid
            out[table] = [{"uid": r["uid"], "name": r["name"], "parent": uids.get(r["parent_id"], ""),
                           "sort": r["sort"], "mtime": r["mtime"], "deleted": bool(r["deleted"])}
                          for r in self.conn.execute(f"SELECT * FROM {table} WHERE dirty=1")]
        out["items"] = []
        for r in self.conn.execute("SELECT * FROM items WHERE dirty=1").fetchall():
            out["items"].append({
                "uid": r["uid"], "name": r["name"], "quantity": r["quantity"],
                "location": loc_uid.get(r["location_id"], ""), "category": cat_uid.get(r["category_id"], ""),
                "price": r["price"], "currency": r["currency"], "notes": r["notes"],
                "created_at": r["created_at"], "photos": [] if r["deleted"] else self.item_photos(r["id"]),
                "shop_name": r["shop_name"], "shop_place": r["shop_place"], "shop_phone": r["shop_phone"],
                "shop_whatsapp": bool(r["shop_whatsapp"]), "shop_telegram": bool(r["shop_telegram"]),
                "mtime": r["mtime"], "deleted": bool(r["deleted"])})
        out["contacts"] = [{
            "uid": r["uid"], "kind": r["kind"], "name": r["name"], "profession": r["profession"],
            "place": r["place"], "phone": r["phone"], "has_whatsapp": bool(r["has_whatsapp"]),
            "has_telegram": bool(r["has_telegram"]), "has_call": bool(r["has_call"]), "notes": r["notes"],
            "created_at": r["created_at"], "photos": [] if r["deleted"] else self.contact_photos(r["id"]),
            "mtime": r["mtime"], "deleted": bool(r["deleted"])}
            for r in self.conn.execute("SELECT * FROM contacts WHERE dirty=1").fetchall()]
        return out

    def mark_clean(self, table, uid, mtime):
        with self.conn:
            self.conn.execute(f"UPDATE {table} SET dirty=0 WHERE uid=? AND mtime=?", (uid, mtime))

    def apply_remote(self, table, records):
        """Buluttan gelen kayıtları birleştirir (son değişiklik kazanır). Değişen kayıt sayısını döndürür."""
        changed = 0
        local = {r["uid"]: r for r in self.conn.execute(f"SELECT uid, mtime, id FROM {table}")}
        accepted = []
        for rec in records:
            cur = local.get(rec["uid"])
            if cur is not None and cur["mtime"] >= rec.get("mtime", ""):
                continue
            accepted.append(rec)
        if not accepted:
            return 0
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
                    vals = (rec.get("name", ""), int(rec.get("quantity") or 0),
                            locs.get(rec.get("location") or ""), cats.get(rec.get("category") or ""),
                            None if price is None else float(price), rec.get("currency") or "TRY",
                            rec.get("notes", ""), rec.get("created_at") or now_str(),
                            rec["mtime"], int(bool(rec.get("deleted"))),
                            *[str(rec.get(f) or "") for f in SHOP_TEXT],
                            *[int(bool(rec.get(f))) for f in SHOP_FLAGS])
                    if rec["uid"] in local:
                        item_id = local[rec["uid"]]["id"]
                        self.conn.execute(
                            "UPDATE items SET name=?, quantity=?, location_id=?, category_id=?, price=?, currency=?, "
                            "notes=?, created_at=?, mtime=?, deleted=?, shop_name=?, shop_place=?, shop_phone=?, "
                            "shop_whatsapp=?, shop_telegram=?, dirty=0 WHERE id=?", (*vals, item_id))
                    else:
                        item_id = self.conn.execute(
                            "INSERT INTO items(name, quantity, location_id, category_id, price, currency, notes, "
                            "created_at, mtime, deleted, shop_name, shop_place, shop_phone, shop_whatsapp, "
                            "shop_telegram, dirty, uid, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                            (*vals, rec["uid"], now_str())).lastrowid
                    old = set(self.item_photos(item_id))
                    new = [] if rec.get("deleted") else list(rec.get("photos") or [])
                    self.conn.execute("DELETE FROM item_photos WHERE item_id=?", (item_id,))
                    self.conn.executemany("INSERT INTO item_photos(item_id, filename, sort) VALUES (?, ?, ?)",
                                          [(item_id, f, i) for i, f in enumerate(new)])
                    self._unlink_photos(old - set(new))
                    changed += 1
            elif table == "contacts":
                for rec in accepted:
                    vals = (rec.get("kind") or "usta", rec.get("name", ""), rec.get("profession", ""),
                            rec.get("place", ""), rec.get("phone", ""), int(bool(rec.get("has_whatsapp"))),
                            int(bool(rec.get("has_telegram"))), int(bool(rec.get("has_call"))),
                            rec.get("notes", ""), rec.get("created_at") or now_str(),
                            rec["mtime"], int(bool(rec.get("deleted"))))
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
                    # 4.0 sürümünden gelen kayıtlarda "photos" alanı yoktur; o zaman fotoğraflara dokunma
                    if "photos" in rec or rec.get("deleted"):
                        old = set(self.contact_photos(cid))
                        new = [] if rec.get("deleted") else list(rec.get("photos") or [])
                        self.conn.execute("DELETE FROM contact_photos WHERE contact_id=?", (cid,))
                        self.conn.executemany("INSERT INTO contact_photos(contact_id, filename, sort) VALUES (?, ?, ?)",
                                              [(cid, f, i) for i, f in enumerate(new)])
                        self._unlink_photos(old - set(new))
                    changed += 1
        return changed

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
