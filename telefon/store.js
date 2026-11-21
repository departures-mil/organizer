/* Organizer — telefon veritabanı (IndexedDB).
 * Kayıtlar masaüstüyle aynı ortak biçimde tutulur: her kaydın uid, mtime (UTC), deleted, dirty alanları vardır.
 * Bütün kayıtlar açılışta belleğe alınır; her değişiklik hemen IndexedDB'ye yazılır. */
"use strict";

const TREE_TABLES = ["locations", "categories"];
const SYNC_TABLES = ["locations", "categories", "items", "contacts"];
const SEED_MTIME = "2000-01-01T00:00:00.000Z";
const CURRENCIES = [["TRY", "₺", "Türk Lirası"], ["USD", "$", "ABD Doları"], ["SYP", "SYP", "Suriye Lirası"]];

const DEFAULT_LOCATIONS = [
  ["Salon", []], ["Mutfak", []], ["Balkon", ["Balkon dolabı"]], ["Banyo", []], ["Banyo üstü", []],
  ["Misafir odası", []], ["Çocuk odası", []], ["Yatak odası", []], ["Koridor", []], ["Kiler / Depo", []],
];
const DEFAULT_CATEGORIES = [
  ["Hırdavat", ["Vidalar", "Somunlar", "Pullar", "Çiviler", "Dübeller", "Menteşeler"]],
  ["Elektrik", ["Kablolar", "Konektörler", "Prizler ve fişler", "Ampuller", "Piller"]],
  ["Aletler", ["El aletleri", "Elektrikli aletler", "Ölçü aletleri"]],
  ["Tesisat", ["Musluk ve bataryalar", "Contalar", "Hortumlar"]],
  ["Boya ve yapıştırıcı", []], ["Mutfak eşyaları", []], ["Ivır zıvır", []],
];

// ------------------------------------------------------------------ yardımcılar
const FOLD = { "ı": "i", "ç": "c", "ğ": "g", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u",
  "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي" };

function norm(text) {
  let s = (text || "").replace(/İ/g, "i").replace(/I/g, "ı").toLowerCase();
  s = s.replace(/[ıçğöşüâîûأإآٱةى]/g, ch => FOLD[ch]);
  return s.replace(/[ً-ْـ]/g, "");
}

function nowUtc() { return new Date().toISOString(); }

// ------------------------------------------------------------------ v.1.0.8: yeni alanlar
// Eski sürümden gelen kayıtta bu alanlar yoksa eldeki değer korunur (applyRemote).
const ITEM_EXTRA = { trashed_at: "", min_qty: 0, to_buy: false, loan_to: "", loan_phone: "", loan_date: "", loan_due: "", loan_history: [] };
const CONTACT_EXTRA = { jobs: [] };
const TRASH_DAYS = 30;
const RECEIPT_PREFIX = "fis-";   // fatura / fiş fotoğrafları (eşitlemede sıradan fotoğraf gibi gider)
const isReceipt = n => String(n || "").startsWith(RECEIPT_PREFIX);
function extraValue(def, v) {
  if (Array.isArray(def)) return Array.isArray(v) ? v : [];
  if (typeof def === "number") return Math.max(0, parseInt(v || 0, 10) || 0);
  if (typeof def === "boolean") return !!v;
  return v == null ? "" : String(v);
}
function todayStr() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
const isLow = d => (parseInt(d.min_qty || 0, 10) || 0) > 0 && (d.quantity || 0) < d.min_qty;
function overdueDays(d) {
  if (!d.loan_to || !/^\d{4}-\d\d-\d\d$/.test(d.loan_due || "")) return 0;
  return Math.floor((new Date(todayStr()) - new Date(d.loan_due)) / 86400000);
}

// Sesli / yazılı soru: "Matkap nerede?" → yalnızca "matkap" aranır; "3 ampul ekle" → yeni eşya
const QUESTION_WORDS = new Set(["nerede", "nerde", "neredeydi", "nerededir", "nereye", "koydum", "koymuştum", "benim", "acaba", "hani",
  "var", "mı", "mi", "where", "is", "are", "the", "my", "did", "i", "put", "a", "an", "أين", "اين", "وين", "فين", "هو", "هي", "ال"].map(w => norm(w)));
const QUESTION_MARKS = new Set(["nerede", "nerde", "neredeydi", "nerededir", "where", "أين", "اين", "وين", "فين"].map(w => norm(w)));
const ADD_WORDS = new Set(["ekle", "ekleyin", "kaydet", "yeni", "add", "new", "save", "أضف", "اضف", "زد", "جديد", "سجل"].map(w => norm(w)));
function parseVoice(text) {
  const words = String(text || "").replace(/[?؟!.,،]+/g, " ").trim().split(/\s+/).filter(Boolean);
  const nw = words.map(w => norm(w));
  let intent = "search";
  if (nw.some(w => QUESTION_MARKS.has(w))) intent = "where";
  else if (nw.some(w => ADD_WORDS.has(w))) intent = "add";
  let qty = null;
  const keep = [];
  words.forEach((w, i) => {
    const n = nw[i];
    if (intent === "add" && ADD_WORDS.has(n)) return;
    if (intent === "where" && QUESTION_WORDS.has(n)) return;
    if (intent === "add" && qty === null && /^\d+$/.test(w)) { qty = parseInt(w, 10); return; }
    keep.push(w);
  });
  return { intent, query: keep.join(" ").trim(), qty };
}
/** Arapçadaki "ال" takısı olmadan da dener (المثقاب → مثقاب) */
const termIn = (term, hay) => hay.includes(term) || (term.length > 3 && term.startsWith("ال") && hay.includes(term.slice(2)));

function pad(n) { return String(n).padStart(2, "0"); }

function nowStr(d) {
  d = d || new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function newUid() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, x => x.toString(16).padStart(2, "0")).join("");
}

function defaultUid(table, trName) {
  const slug = norm(trName).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `def-${table === "locations" ? "loc" : "cat"}-${slug}`;
}

function phoneForLinks(phone, cc) {
  const p = (phone || "").trim();
  const digits = p.replace(/\D/g, "");
  if (!digits) return "";
  if (p.startsWith("+")) return digits;
  if (digits.startsWith("00")) return digits.slice(2);
  if (digits.startsWith("0")) return cc + digits.slice(1);
  if (digits.length <= 10) return cc + digits;
  return digits;
}

/** Sıralama: "<alan>_asc" / "<alan>_desc" (eski adlar da geçerli); boş değerler her iki yönde en sonda. */
const SORT_ALIASES = { newest: "created_desc", oldest: "created_asc", category: "category_asc", location: "location_asc" };
function shopTitle(d) {
  return String(d.shop_name || "").trim() || String(d.shop_place || "").trim() || String(d.shop_phone || "").trim();
}

function sortRecords(rows, sort, fields, empty) {
  sort = SORT_ALIASES[sort] || sort || "created_desc";
  const i = sort.lastIndexOf("_");
  let field = sort.slice(0, i), dir = sort.slice(i + 1);
  if (!fields[field]) { field = fields.created && fields.qty ? "created" : "name"; dir = field === "created" ? "desc" : "asc"; }
  const key = fields[field], isEmpty = (empty || {})[field] || (() => false), name = fields.name || (() => "");
  const cmpv = (a, b) => {
    if (Array.isArray(a)) { for (let k = 0; k < a.length; k++) { const c = cmpv(a[k], b[k]); if (c) return c; } return 0; }
    return a < b ? -1 : a > b ? 1 : 0;
  };
  const sign = dir === "desc" ? -1 : 1;
  const full = rows.filter(d => !isEmpty(d)), blank = rows.filter(d => isEmpty(d));
  full.sort((a, b) => sign * cmpv(key(a), key(b)) || cmpv(name(a), name(b)));
  blank.sort((a, b) => cmpv(name(a), name(b)));
  return full.concat(blank);
}

function reqP(req) {
  return new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); });
}

// ------------------------------------------------------------------ veritabanı
const Store = {
  idb: null,
  t: { locations: new Map(), categories: new Map(), items: new Map(), contacts: new Map() },
  settings: {},
  photoSync: new Map(),
  listeners: [],

  async open(name) {
    this.idb = await new Promise((res, rej) => {
      // Sürüm 2 (uygulama 4.1): meslek simgeleri deposu eklendi. Var olan depolara dokunulmaz, kayıtlar korunur.
      const r = indexedDB.open(name || "organizer", 2);
      r.onupgradeneeded = () => {
        const db = r.result;
        const want = [...SYNC_TABLES.map(s => [s, "uid"]), ["photos", "name"], ["thumbs", "name"],
          ["settings", "key"], ["photo_sync", "name"], ["icons", "slug"]];
        for (const [s, key] of want) if (!db.objectStoreNames.contains(s)) db.createObjectStore(s, { keyPath: key });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    const tx = this.idb.transaction([...SYNC_TABLES, "settings", "photo_sync"], "readonly");
    for (const s of SYNC_TABLES) {
      for (const rec of await reqP(tx.objectStore(s).getAll())) this.t[s].set(rec.uid, rec);
    }
    for (const r of await reqP(tx.objectStore("settings").getAll())) this.settings[r.key] = r.value;
    for (const r of await reqP(tx.objectStore("photo_sync").getAll())) this.photoSync.set(r.name, r.state);
  },

  async _put(store, values) {
    if (!values.length) return;
    const tx = this.idb.transaction(store, "readwrite");
    const os = tx.objectStore(store);
    for (const v of values) os.put(v);
    await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = () => rej(tx.error); tx.onabort = () => rej(tx.error); });
  },

  async _del(store, keys) {
    if (!keys.length) return;
    const tx = this.idb.transaction(store, "readwrite");
    for (const k of keys) tx.objectStore(store).delete(k);
    await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  },

  async save(table, recs) {
    recs = Array.isArray(recs) ? recs : [recs];
    for (const r of recs) this.t[table].set(r.uid, r);
    await this._put(table, recs);
    this.changed(table);
  },

  changed(what) { for (const f of this.listeners) f(what); },

  get(key, def) { return key in this.settings && this.settings[key] !== null ? this.settings[key] : def; },

  async set(key, value) {
    this.settings[key] = value;
    if (value === null || value === undefined) await this._del("settings", [key]);
    else await this._put("settings", [{ key, value }]);
  },

  async seed(lang) {
    if (this.get("seeded")) return;
    const recs = { locations: [], categories: [] };
    for (const [table, data] of [["locations", DEFAULT_LOCATIONS], ["categories", DEFAULT_CATEGORIES]]) {
      data.forEach(([name, children], i) => {
        const uid = defaultUid(table, name);
        recs[table].push({ uid, name: defaultName(name, lang), parent: "", sort: i, mtime: SEED_MTIME, deleted: false, dirty: true });
        children.forEach((child, j) => recs[table].push({
          uid: defaultUid(table, child), name: defaultName(child, lang), parent: uid, sort: j,
          mtime: SEED_MTIME, deleted: false, dirty: true }));
      });
      // Bulutta zaten varsa (başka cihazdan) üzerine yazmayalım
      await this.save(table, recs[table].filter(r => !this.t[table].has(r.uid)));
    }
    await this.set("seeded", "1");
  },

  // -------------------------------------------------------------- ağaçlar
  treeRows(table) {
    return [...this.t[table].values()].filter(r => !r.deleted)
      .sort((a, b) => (a.sort - b.sort) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  },

  /** [{uid, name, depth, path}] derinlik öncelikli sırayla */
  treeOrdered(table) {
    const rows = this.treeRows(table);
    const ids = new Set(rows.map(r => r.uid));
    const children = new Map();
    for (const r of rows) {
      const p = ids.has(r.parent) && r.parent !== r.uid ? r.parent : "";
      if (!children.has(p)) children.set(p, []);
      children.get(p).push(r);
    }
    const out = [];
    const seen = new Set();
    const walk = (parent, depth, prefix) => {
      for (const r of children.get(parent) || []) {
        if (seen.has(r.uid)) continue;
        seen.add(r.uid);
        const path = prefix ? `${prefix} › ${r.name}` : r.name;
        out.push({ uid: r.uid, name: r.name, depth, path, parent: parent });
        walk(r.uid, depth + 1, path);
      }
    };
    walk("", 0, "");
    return out;
  },

  treePaths(table) {
    const m = new Map();
    for (const n of this.treeOrdered(table)) m.set(n.uid, n.path);
    return m;
  },

  descendants(table, uid) {
    const kids = new Map();
    for (const r of this.treeRows(table)) {
      if (!kids.has(r.parent)) kids.set(r.parent, []);
      kids.get(r.parent).push(r.uid);
    }
    const out = new Set();
    const stack = [uid];
    while (stack.length) {
      const n = stack.pop();
      if (out.has(n)) continue;
      out.add(n);
      stack.push(...(kids.get(n) || []));
    }
    return out;
  },

  async addNode(table, name, parent) {
    parent = parent || "";
    const sibs = this.treeRows(table).filter(r => r.parent === parent);
    const sort = sibs.reduce((m, r) => Math.max(m, r.sort), -1) + 1;
    const rec = { uid: newUid(), name: name.trim(), parent, sort, mtime: nowUtc(), deleted: false, dirty: true };
    await this.save(table, rec);
    return rec.uid;
  },

  async renameNode(table, uid, name) {
    const r = this.t[table].get(uid);
    await this.save(table, { ...r, name: name.trim(), mtime: nowUtc(), dirty: true });
  },

  async setParent(table, uid, parent) {
    const r = this.t[table].get(uid);
    if (this.descendants(table, uid).has(parent)) return;
    const sibs = this.treeRows(table).filter(x => x.parent === parent && x.uid !== uid);
    const sort = sibs.reduce((m, x) => Math.max(m, x.sort), -1) + 1;
    await this.save(table, { ...r, parent, sort, mtime: nowUtc(), dirty: true });
  },

  async moveNode(table, uid, delta) {
    const r = this.t[table].get(uid);
    const sibs = this.treeRows(table).filter(x => x.parent === r.parent).map(x => x.uid);
    const i = sibs.indexOf(uid), j = i + delta;
    if (j < 0 || j >= sibs.length) return;
    [sibs[i], sibs[j]] = [sibs[j], sibs[i]];
    const ts = nowUtc();
    const changed = [];
    sibs.forEach((u, k) => {
      const x = this.t[table].get(u);
      if (x.sort !== k) changed.push({ ...x, sort: k, mtime: ts, dirty: true });
    });
    await this.save(table, changed);
  },

  itemsUnder(table, uid) {
    const ids = this.descendants(table, uid);
    const col = table === "locations" ? "location" : "category";
    return this.liveItems().filter(i => ids.has(i[col])).length;
  },

  async deleteNode(table, uid) {
    const r = this.t[table].get(uid);
    const ids = this.descendants(table, uid);
    const col = table === "locations" ? "location" : "category";
    const ts = nowUtc();
    await this.save("items", this.liveItems().filter(i => ids.has(i[col]))
      .map(i => ({ ...i, [col]: r.parent || "", mtime: ts, dirty: true })));
    await this.save(table, [...ids].map(u => this.t[table].get(u)).filter(Boolean)
      .map(x => ({ ...x, deleted: true, mtime: ts, dirty: true })));
  },

  itemCounts(table) {
    const col = table === "locations" ? "location" : "category";
    const m = new Map();
    for (const i of this.liveItems()) m.set(i[col] || "", (m.get(i[col] || "") || 0) + 1);
    return m;
  },

  async translateDefaults(oldLang, newLang) {
    const changed = { locations: [], categories: [] };
    for (const table of TREE_TABLES) {
      for (const r of this.treeRows(table)) {
        for (const tr of Object.keys(I18N.defaults)) {
          if (r.name === defaultName(tr, oldLang)) {
            changed[table].push({ ...r, name: defaultName(tr, newLang) });  // mtime/dirty değişmez
            break;
          }
        }
      }
      await this.save(table, changed[table]);
    }
  },

  // -------------------------------------------------------------- eşyalar
  liveItems() { return [...this.t.items.values()].filter(i => !i.deleted && !i.trashed_at); },
  trashItemsList() { return [...this.t.items.values()].filter(i => !i.deleted && i.trashed_at); },

  listItems({ search = "", categories = null, locations = null, sort = "newest", trashed = false } = {}) {
    const catPaths = this.treePaths("categories"), locPaths = this.treePaths("locations");
    const terms = norm(search).split(/\s+/).filter(w => w && !QUESTION_WORDS.has(w));
    const out = [];
    for (const r of (trashed ? this.trashItemsList() : this.liveItems())) {
      const cat = catPaths.has(r.category) ? r.category : "";
      const loc = locPaths.has(r.location) ? r.location : "";
      if (categories && !categories.has(cat)) continue;
      if (locations && !locations.has(loc)) continue;
      const d = { ...r, category: cat, location: loc, category_path: catPaths.get(cat) || "", location_path: locPaths.get(loc) || "" };
      if (terms.length) {
        const hay = norm([d.name, d.notes, d.category_path, d.location_path, d.shop_name, d.shop_place, d.shop_phone, d.loan_to,
          String(d.shop_phone || "").replace(/\D/g, "")].join(" "));
        if (!terms.every(t => termIn(t, hay))) continue;
      }
      out.push(d);
    }
    return sortRecords(out, sort, {
      created: d => d.created_at, name: d => norm(d.name), qty: d => d.quantity,
      price: d => [d.currency, d.price], category: d => norm(d.category_path), location: d => norm(d.location_path),
      shop: d => norm(shopTitle(d)), place: d => norm(d.shop_place || ""), trashed: d => d.trashed_at || "",
    }, { price: d => d.price == null, category: d => !d.category_path, location: d => !d.location_path, shop: d => !shopTitle(d),
      place: d => !String(d.shop_place || "").trim() });
  },

  /** Daha önce girilmiş dükkanlar (eşyalardan ve dükkan kayıtlarından): ad → yer / numara / uygulamalar */
  knownShops() {
    const m = new Map();
    for (const c of this.t.contacts.values()) {
      if (c.deleted || c.kind !== "dukkan" || !c.name) continue;
      m.set(c.name, { shop_place: c.place || "", shop_phone: c.phone || "", shop_whatsapp: !!c.has_whatsapp, shop_telegram: !!c.has_telegram });
    }
    const items = this.liveItems().filter(i => i.shop_name).sort((a, b) => (a.mtime < b.mtime ? -1 : 1));
    for (const i of items) m.set(i.shop_name, { shop_place: i.shop_place || "", shop_phone: i.shop_phone || "",
      shop_whatsapp: !!i.shop_whatsapp, shop_telegram: !!i.shop_telegram });
    return m;
  },

  totals(items) {
    const m = {};
    for (const d of items) if (d.price != null) m[d.currency] = (m[d.currency] || 0) + d.price;
    return m;
  },

  /** data: name, quantity, category, location, price, currency, notes, created_at; photos: [dosya adı] */
  async saveItem(data, photos, uid) {
    const old = uid ? this.t.items.get(uid) : null;
    const rec = {
      uid: uid || newUid(), name: data.name.trim(), quantity: Math.max(0, parseInt(data.quantity, 10) || 0),
      category: data.category || "", location: data.location || "",
      price: data.price == null || data.price === "" ? null : Number(data.price), currency: data.currency || "TRY",
      notes: data.notes || "", created_at: data.created_at || nowStr(), updated_at: nowStr(),
      shop_name: (data.shop_name || "").trim(), shop_place: (data.shop_place || "").trim(), shop_phone: (data.shop_phone || "").trim(),
      shop_whatsapp: !!data.shop_whatsapp, shop_telegram: !!data.shop_telegram,
      price_auto: !!data.price_auto && !(data.price == null || data.price === ""),
      photos: photos, mtime: nowUtc(), deleted: false, dirty: true,
    };
    // v.1.0.8 alanları: formda olmayanlar (çöp, ödünç, liste…) eldeki kayıttan korunur
    for (const [f, def] of Object.entries(ITEM_EXTRA)) rec[f] = extraValue(def, f in data ? data[f] : (old ? old[f] : def));
    await this.save("items", rec);
    if (old) await this._dropPhotos(old.photos.filter(p => !photos.includes(p)));
    return rec.uid;
  },

  async updateItems(uids, field, value) {
    const ts = nowUtc();
    await this.save("items", uids.map(u => ({ ...this.t.items.get(u), [field]: value, updated_at: nowStr(), mtime: ts, dirty: true })));
  },

  async changeQuantity(uid, delta) {
    const r = this.t.items.get(uid);
    await this.save("items", { ...r, quantity: Math.max(0, r.quantity + delta), updated_at: nowStr(), mtime: nowUtc(), dirty: true });
  },

  // -------------------------------------------------------------- çöp kutusu (v.1.0.8)
  async trashItems(uids) {
    const ts = nowUtc();
    await this.save("items", uids.map(u => this.t.items.get(u)).filter(Boolean)
      .map(r => ({ ...r, trashed_at: ts, mtime: ts, dirty: true })));
  },

  async restoreItems(uids) {
    const ts = nowUtc();
    await this.save("items", uids.map(u => this.t.items.get(u)).filter(Boolean)
      .map(r => ({ ...r, trashed_at: "", mtime: ts, dirty: true })));
  },

  async purgeOldTrash() {
    const limit = new Date(Date.now() - TRASH_DAYS * 86400000).toISOString();
    const old = this.trashItemsList().filter(r => r.trashed_at < limit).map(r => r.uid);
    if (old.length) await this.purgeItems(old);
    return old.length;
  },

  // -------------------------------------------------------------- ödünç / stok / geri al (v.1.0.8)
  async patchItems(uids, patch) {
    const ts = nowUtc();
    await this.save("items", uids.map(u => this.t.items.get(u)).filter(Boolean)
      .map(r => ({ ...r, ...(typeof patch === "function" ? patch(r) : patch), updated_at: nowStr(), mtime: ts, dirty: true })));
  },

  async lend(uid, to, phone, date, due) {
    await this.patchItems([uid], { loan_to: to.trim(), loan_phone: (phone || "").trim(), loan_date: date || todayStr(), loan_due: due || "" });
  },

  async giveBack(uid) {
    await this.patchItems([uid], r => ({ loan_to: "", loan_phone: "", loan_date: "", loan_due: "",
      loan_history: [...(r.loan_history || []), { to: r.loan_to, phone: r.loan_phone || "", date: r.loan_date || "",
        due: r.loan_due || "", returned: todayStr() }].slice(-50) }));
  },

  shoppingList() { return this.listItems({ sort: "name_asc" }).filter(d => d.to_buy || isLow(d)); },

  async bought(uid, n) {
    await this.patchItems([uid], r => ({ quantity: (r.quantity || 0) + Math.max(0, n | 0), to_buy: false }));
  },

  snapshot(uids) { return uids.map(u => this.t.items.get(u)).filter(Boolean).map(r => JSON.parse(JSON.stringify(r))); },

  async restoreSnapshot(snap) {
    const ts = nowUtc();
    const recs = [];
    for (const r of snap) {
      const photos = [];
      for (const p of r.photos || []) if (await this.hasPhoto(p)) photos.push(p);
      for (const p of photos) if (this.photoSync.get(p) === "delete") await this.setPhotoState(p, null);
      recs.push({ ...r, photos, mtime: ts, dirty: true });
    }
    await this.save("items", recs);
  },

  async saveJobs(uid, jobs) {
    const c = this.t.contacts.get(uid);
    if (c) await this.save("contacts", { ...c, jobs, mtime: nowUtc(), dirty: true });
  },

  /** Kalıcı silme (geri alınamaz) */
  async purgeItems(uids) {
    const ts = nowUtc();
    const photos = [];
    const recs = uids.map(u => {
      const r = this.t.items.get(u);
      photos.push(...r.photos);
      return { ...r, photos: [], deleted: true, mtime: ts, dirty: true };
    });
    await this.save("items", recs);
    await this._dropPhotos(photos);
  },

  // -------------------------------------------------------------- fotoğraflar
  async addPhoto(blob, thumb, prefix) {
    const name = (prefix || "") + newUid() + ".jpg";
    await this._put("photos", [{ name, blob }]);
    if (thumb) await this._put("thumbs", [{ name, blob: thumb }]);
    return name;
  },

  async photoBlob(name, thumb) {
    const tx = this.idb.transaction(thumb ? "thumbs" : "photos", "readonly");
    const r = await reqP(tx.objectStore(thumb ? "thumbs" : "photos").get(name));
    return r ? r.blob : null;
  },

  async hasPhoto(name) {
    const tx = this.idb.transaction("photos", "readonly");
    return (await reqP(tx.objectStore("photos").count(name))) > 0;
  },

  async _removePhotoData(names) {
    await this._del("photos", names);
    await this._del("thumbs", names);
    PhotoCache.forget(names);
  },

  async _dropPhotos(names) {
    if (!names.length) return;
    await this._removePhotoData(names);
    for (const n of names) this.photoSync.set(n, "delete");
    await this._put("photo_sync", names.map(n => ({ name: n, state: "delete" })));
  },

  async setPhotoState(name, state) {
    if (state == null) { this.photoSync.delete(name); await this._del("photo_sync", [name]); }
    else { this.photoSync.set(name, state); await this._put("photo_sync", [{ name, state }]); }
  },

  // -------------------------------------------------------------- ustalar
  listContacts({ search = "", kind = null, sort = "name_asc" } = {}) {
    const terms = norm(search).split(/\s+/).filter(Boolean);
    const out = [...this.t.contacts.values()].filter(d => {
      if (d.deleted || (kind && d.kind !== kind)) return false;
      if (!terms.length) return true;
      const hay = norm([d.name, d.profession, d.place, d.phone, (d.phone || "").replace(/\D/g, ""), d.notes,
        ...(d.jobs || []).map(j => j.work || "")].join(" "));
      return terms.every(t => hay.includes(t));
    });
    return sortRecords(out, sort, {
      name: d => norm(d.name), kind: d => [d.kind, norm(d.name)], prof: d => norm(d.profession || ""),
      place: d => norm(d.place || ""), phone: d => (d.phone || "").replace(/\D/g, ""), notes: d => norm(d.notes || ""),
      created: d => d.created_at || "",
    }, { prof: d => !d.profession, place: d => !d.place, phone: d => !d.phone, notes: d => !d.notes });
  },

  /** photos: [dosya adı] ya da undefined (dokunma) */
  async saveContact(data, uid, photos) {
    const old = uid ? this.t.contacts.get(uid) : null;
    if (photos === undefined) photos = old ? (old.photos || []) : [];
    const rec = {
      jobs: extraValue([], "jobs" in data ? data.jobs : (old ? old.jobs : [])),
      uid: uid || newUid(), kind: data.kind || "usta", name: data.name.trim(), profession: (data.profession || "").trim(),
      place: (data.place || "").trim(), phone: (data.phone || "").trim(), has_whatsapp: !!data.has_whatsapp,
      has_telegram: !!data.has_telegram, has_call: !!data.has_call, notes: data.notes || "",
      created_at: old ? old.created_at : nowStr(), photos, mtime: nowUtc(), deleted: false, dirty: true,
    };
    await this.save("contacts", rec);
    if (old) await this._dropPhotos((old.photos || []).filter(p => !photos.includes(p)));
    return rec.uid;
  },

  async deleteContacts(uids) {
    const ts = nowUtc();
    const photos = [];
    await this.save("contacts", uids.map(u => {
      const c = this.t.contacts.get(u);
      photos.push(...(c.photos || []));
      return { ...c, photos: [], deleted: true, mtime: ts, dirty: true };
    }));
    await this._dropPhotos(photos);
  },

  professions() {
    const s = new Set();
    for (const c of this.t.contacts.values()) if (!c.deleted && c.profession) s.add(c.profession);
    return [...s].sort();
  },

  // -------------------------------------------------------------- eşitleme
  dirtyRecords() {
    const out = {};
    for (const table of SYNC_TABLES) {
      out[table] = [...this.t[table].values()].filter(r => r.dirty).map(r => {
        const { dirty, updated_at, ...rest } = r;  // eslint-disable-line no-unused-vars
        if (table === "items" || table === "contacts") rest.photos = r.deleted ? [] : (r.photos || []);
        rest.deleted = !!r.deleted;
        return rest;
      });
    }
    return out;
  },

  async markClean(table, uid, mtime) {
    const r = this.t[table].get(uid);
    if (r && r.mtime === mtime && r.dirty) {
      r.dirty = false;
      await this._put(table, [r]);
    }
  },

  /** Bütün kayıtlar (silinmişler dahil) — yerel ağ eşitlemesi için */
  allRecords() {
    const out = {};
    for (const table of SYNC_TABLES) out[table] = [...this.t[table].values()].map(r => {
      const { dirty, updated_at, ...rest } = r;  // eslint-disable-line no-unused-vars
      if (table === "items" || table === "contacts") rest.photos = r.deleted ? [] : (r.photos || []);
      rest.deleted = !!r.deleted;
      return rest;
    });
    return out;
  },

  /** Buluttan (ya da yerel ağdan) gelen kayıtları birleştirir (son değişiklik kazanır).
   *  keepDirty: kabul edilenler buluta da gönderilsin (yerel ağdan gelenler). */
  async applyRemote(table, records, keepDirty) {
    const accepted = [];
    const dropPhotos = [];
    for (const rec of records) {
      const cur = this.t[table].get(rec.uid);
      if (cur && cur.mtime >= (rec.mtime || "")) {
        // aynı sürüm: eski sürümün düşürdüğü "otomatik fiyat" işaretini tamamla
        if (table === "items" && cur.mtime === rec.mtime && "price_auto" in rec && !!cur.price_auto !== !!rec.price_auto)
          accepted.push({ ...cur, price_auto: !!rec.price_auto });
        continue;
      }
      let r;
      if (TREE_TABLES.includes(table)) {
        r = { uid: rec.uid, name: rec.name || "", parent: rec.parent === rec.uid ? "" : (rec.parent || ""),
          sort: parseInt(rec.sort || 0, 10), mtime: rec.mtime, deleted: !!rec.deleted, dirty: false };
      } else if (table === "items") {
        const photos = rec.deleted ? [] : (rec.photos || []);
        if (cur) dropPhotos.push(...cur.photos.filter(p => !photos.includes(p)));
        r = { uid: rec.uid, name: rec.name || "", quantity: parseInt(rec.quantity || 0, 10), category: rec.category || "",
          location: rec.location || "", price: rec.price == null ? null : Number(rec.price), currency: rec.currency || "TRY",
          notes: rec.notes || "", created_at: rec.created_at || nowStr(), updated_at: nowStr(), photos,
          mtime: rec.mtime, deleted: !!rec.deleted, dirty: false };
        // 1.4.0 öncesi bir cihazdan gelen kayıtta satın alma yeri yoksa eldeki bilgi korunur
        const src = "shop_name" in rec ? rec : (cur || {});
        Object.assign(r, { shop_name: src.shop_name || "", shop_place: src.shop_place || "", shop_phone: src.shop_phone || "",
          shop_whatsapp: !!src.shop_whatsapp, shop_telegram: !!src.shop_telegram });
        // otomatik (tahmini) fiyat işareti; bilmeyen eski sürümden gelirse fiyat aynıysa eldeki işaret korunur
        r.price_auto = r.price != null && ("price_auto" in rec ? !!rec.price_auto
          : !!(cur && cur.price_auto && cur.price != null && Math.abs(cur.price - r.price) < 1e-9));
        for (const [f, def] of Object.entries(ITEM_EXTRA)) r[f] = extraValue(def, f in rec ? rec[f] : (cur ? cur[f] : def));
      } else {
        // 4.0 sürümünden gelen kayıtlarda "photos" alanı yoktur; o zaman eldeki fotoğraflar kalır
        const photos = rec.deleted ? [] : ("photos" in rec ? (rec.photos || []) : (cur ? (cur.photos || []) : []));
        if (cur) dropPhotos.push(...(cur.photos || []).filter(p => !photos.includes(p)));
        r = { photos, uid: rec.uid, kind: rec.kind || "usta", name: rec.name || "", profession: rec.profession || "",
          place: rec.place || "", phone: rec.phone || "", has_whatsapp: !!rec.has_whatsapp, has_telegram: !!rec.has_telegram,
          has_call: !!rec.has_call, notes: rec.notes || "", created_at: rec.created_at || nowStr(),
          mtime: rec.mtime, deleted: !!rec.deleted, dirty: false };
        r.jobs = extraValue([], "jobs" in rec ? rec.jobs : (cur ? cur.jobs : []));
      }
      if (keepDirty) r.dirty = true;
      accepted.push(r);
    }
    await this.save(table, accepted);
    if (dropPhotos.length) await this._removePhotoData(dropPhotos);
    return accepted.length;
  },

  /** Eşya ve usta/dükkan fotoğrafları: [[dosya, sahibin uid'si]] */
  allPhotos() {
    const out = [];
    for (const i of this.liveItems()) for (const p of i.photos) out.push([p, i.uid]);
    for (const c of this.t.contacts.values()) if (!c.deleted) for (const p of c.photos || []) out.push([p, c.uid]);
    return out;
  },

  photosToUpload() { return this.allPhotos().filter(([p]) => !this.photoSync.has(p)); },

  photosToDelete() { return [...this.photoSync].filter(([, s]) => s === "delete").map(([n]) => n); },

  async missingPhotos() {
    const out = [];
    for (const [p] of this.allPhotos()) if (!(await this.hasPhoto(p))) out.push(p);
    return out;
  },

  async resetSyncState() {
    for (const table of SYNC_TABLES) {
      const recs = [...this.t[table].values()].map(r => ({ ...r, dirty: true }));
      for (const r of recs) this.t[table].set(r.uid, r);
      await this._put(table, recs);
    }
    await this._del("photo_sync", [...this.photoSync.keys()]);
    this.photoSync.clear();
    for (const k of Object.keys(this.settings)) if (k.startsWith("sync_cursor_")) await this.set(k, null);
  },

  // -------------------------------------------------------------- meslek simgeleri (bu cihazda önbellek)
  async getIcon(slug) {
    const tx = this.idb.transaction("icons", "readonly");
    const r = await reqP(tx.objectStore("icons").get(slug));
    return r ? r.svg : null;
  },
  async putIcon(slug, svg) { await this._put("icons", [{ slug, svg }]); },

  // -------------------------------------------------------------- yedek
  async exportAll() {
    const data = { app: "Organizer", version: APP_VERSION, exported_at: nowStr(), tables: {}, photos: {} };
    for (const table of SYNC_TABLES) data.tables[table] = [...this.t[table].values()];
    for (const [p] of this.allPhotos()) {
      const b = await this.photoBlob(p);
      if (b) data.photos[p] = await blobToBase64(b);
    }
    return JSON.stringify(data);
  },
};

function blobToBase64(blob) {
  return new Promise(res => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1] || "");
    r.readAsDataURL(blob);
  });
}

function base64ToBlob(b64, type) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type: type || "image/jpeg" });
}

/** Fotoğraf görüntüleri için object URL önbelleği */
const PhotoCache = {
  urls: new Map(),
  async url(name, thumb) {
    const key = (thumb ? "t:" : "f:") + name;
    if (this.urls.has(key)) return this.urls.get(key);
    let blob = await Store.photoBlob(name, thumb);
    if (!blob && thumb) blob = await Store.photoBlob(name, false);
    if (!blob) return null;
    const u = URL.createObjectURL(blob);
    this.urls.set(key, u);
    return u;
  },
  forget(names) {
    for (const n of names) for (const k of ["t:" + n, "f:" + n]) {
      if (this.urls.has(k)) { URL.revokeObjectURL(this.urls.get(k)); this.urls.delete(k); }
    }
  },
};
