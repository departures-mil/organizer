/* Organizer — Firebase (Firestore) eşitlemesi. Masaüstündeki organizer/sync.py ile birebir aynı biçim. */
"use strict";

const MAX_PHOTO_BYTES = 900000;
const PHOTO_MAX_SIDE = 1600;

class SyncError extends Error {
  constructor(code, detail) { super(`${code}: ${detail || ""}`); this.code = code; this.detail = detail || ""; }
}

/* v.1.0.10: Programla gelen ortak Firebase projesi KALDIRILDI — herkes kendi ücretsiz Firebase hesabını kullanır
 * (yöneticinin günlük sınırı başkalarınca harcanmasın). Eski ortak projeye bağlı yönetici hesabı aynen devam eder. */
const DEFAULT_FB_CONFIG = "";
const FB_REHBER = "https://github.com/departures-mil/duyurular/blob/main/firebase-kurulum.md";
const ESKI_ORTAK_FB = `const firebaseConfig = {
  apiKey: "AIzaSyDWK8jDUdNW0k3vwHDbNBgud6gTEIdqhcg",
  authDomain: "duzenli-evim.firebaseapp.com",
  projectId: "duzenli-evim",
  storageBucket: "duzenli-evim.firebasestorage.app",
  messagingSenderId: "1059030151497",
  appId: "1:1059030151497:web:0e320562bdc00ff4a7aa98"
};`;
// Yönetici e-postası depoda düz metin tutulmaz: yalnız SHA-256 özeti (küçük harf, boşluksuz) karşılaştırılır.
const YONETICI_SHA256 = "b1acd212aa26e8d1a66302ca74cf125228fea1e0cf805377ddcaabb5278722c1";
function sha256Hex(str) {           // eşzamanlı, küçük SHA-256 (UTF-8)
  const K = [], H = [];
  const isP = n => { for (let i = 2; i * i <= n; i++) if (n % i === 0) return false; return true; };
  const frac = x => ((x - Math.floor(x)) * 0x100000000) | 0;
  for (let n = 2, c = 0; c < 64; n++) if (isP(n)) { if (c < 8) H[c] = frac(Math.pow(n, 1 / 2)); K[c++] = frac(Math.pow(n, 1 / 3)); }
  const b = Array.from(new TextEncoder().encode(str)), bitLen = b.length * 8;
  b.push(0x80); while (b.length % 64 !== 56) b.push(0);
  for (let i = 7; i >= 0; i--) b.push(i > 3 ? 0 : (bitLen >>> (i * 8)) & 0xff);
  const w = new Array(64), r = (x, n) => (x >>> n) | (x << (32 - n));
  for (let o = 0; o < b.length; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = (b[o + 4 * i] << 24) | (b[o + 4 * i + 1] << 16) | (b[o + 4 * i + 2] << 8) | b[o + 4 * i + 3];
    for (let i = 16; i < 64; i++) {
      const s0 = r(w[i - 15], 7) ^ r(w[i - 15], 18) ^ (w[i - 15] >>> 3), s1 = r(w[i - 2], 17) ^ r(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let [a, bb, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
      const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c))) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = bb; bb = a; a = (t1 + t2) | 0;
    }
    [a, bb, c, d, e, f, g, h].forEach((v, i) => { H[i] = (H[i] + v) | 0; });
  }
  return H.map(v => (v >>> 0).toString(16).padStart(8, "0")).join("");
}

function parseConfig(text) {
  text = text || "";
  try {
    const d = JSON.parse(text);
    if (d && d.apiKey && d.projectId) return { apiKey: d.apiKey, projectId: d.projectId };
  } catch (e) { /* firebaseConfig JS parçası olabilir */ }
  const out = {};
  for (const key of ["apiKey", "projectId"]) {
    const m = text.match(new RegExp(key + "\\s*[\"']?\\s*:\\s*[\"']([^\"']+)[\"']"));
    if (m) out[key] = m[1].trim();
  }
  if (!out.apiKey || !out.projectId) throw new SyncError("config");
  return out;
}

function toValue(v) {
  if (v === null || v === undefined) return { nullValue: null };
  if (typeof v === "boolean") return { booleanValue: v };
  if (typeof v === "number") return Number.isInteger(v) && !v.__float ? { integerValue: String(v) } : { doubleValue: v };
  if (v instanceof Bytes) return { bytesValue: v.b64 };
  if (Array.isArray(v)) return { arrayValue: { values: v.map(toValue) } };
  if (typeof v === "object") {
    const f = {};
    for (const [k, x] of Object.entries(v)) f[k] = toValue(x);
    return { mapValue: { fields: f } };
  }
  return { stringValue: String(v) };
}

function fromValue(v) {
  if ("nullValue" in v) return null;
  if ("booleanValue" in v) return v.booleanValue;
  if ("integerValue" in v) return parseInt(v.integerValue, 10);
  if ("doubleValue" in v) return Number(v.doubleValue);
  if ("stringValue" in v) return v.stringValue;
  if ("timestampValue" in v) return v.timestampValue;
  if ("bytesValue" in v) return new Bytes(v.bytesValue);
  if ("arrayValue" in v) return (v.arrayValue.values || []).map(fromValue);
  if ("mapValue" in v) {
    const o = {};
    for (const [k, x] of Object.entries(v.mapValue.fields || {})) o[k] = fromValue(x);
    return o;
  }
  return null;
}

class Bytes { constructor(b64) { this.b64 = b64; } }

function tsKey(ts) {
  if (!ts) return "";
  const m = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z?$/.exec(ts);
  if (!m) return ts;
  return m[1] + "." + (m[2] || "").padEnd(9, "0").slice(0, 9);
}

class FirebaseClient {
  constructor(config, emulator) {
    this.apiKey = config.apiKey;
    this.project = config.projectId;
    emulator = emulator || (typeof localStorage !== "undefined" && localStorage.getItem("fb_emulator"));
    if (emulator) {
      emulator = emulator.replace(/\/+$/, "");
      this.authBase = `${emulator}/identitytoolkit/v1`;
      this.tokenUrl = `${emulator}/securetoken/v1/token`;
      this.fsRoot = `${emulator}/firestore/v1`;
    } else {
      this.authBase = "https://identitytoolkit.googleapis.com/v1";
      this.tokenUrl = "https://securetoken.googleapis.com/v1/token";
      this.fsRoot = "https://firestore.googleapis.com/v1";
    }
    this.dbPath = `projects/${this.project}/databases/(default)/documents`;
    this.idToken = null; this.expires = 0; this.refreshToken = null; this.uid = null; this.email = null;
  }

  async _request(method, url, body, { form = false, auth = true } = {}) {
    const headers = {};
    let data;
    if (body !== undefined) {
      if (form) {
        data = new URLSearchParams(body).toString();
        headers["Content-Type"] = "application/x-www-form-urlencoded";
      } else {
        data = JSON.stringify(body);
        headers["Content-Type"] = "application/json";
      }
    }
    if (auth) headers.Authorization = `Bearer ${await this._token()}`;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 60000);
    let r;
    try {
      r = await fetch(url, { method, headers, body: data, signal: ctl.signal });
    } catch (e) {
      throw new SyncError("network", String(e));
    } finally {
      clearTimeout(timer);
    }
    const raw = await r.text();
    if (!r.ok) {
      let msg = "";
      try {
        const err = JSON.parse(raw);
        msg = typeof err.error === "object" ? (err.error.message || "") : String(err.error || "");
      } catch (e) { /* boş */ }
      if (r.status === 404) throw new SyncError("not_found", msg);
      if (!auth || r.status === 401 || r.status === 403) throw new SyncError("auth", msg || String(r.status));
      throw new SyncError("server", msg || String(r.status));
    }
    return raw ? JSON.parse(raw) : {};
  }

  _setSession(idToken, refreshToken, uid, expiresIn, email) {
    this.idToken = idToken; this.refreshToken = refreshToken; this.uid = uid;
    this.expires = Date.now() + (parseInt(expiresIn, 10) - 120) * 1000;
    if (email) this.email = email;
  }

  async signIn(email, password, create) {
    const op = create ? "signUp" : "signInWithPassword";
    const r = await this._request("POST", `${this.authBase}/accounts:${op}?key=${this.apiKey}`,
      { email, password, returnSecureToken: true }, { auth: false });
    this._setSession(r.idToken, r.refreshToken, r.localId, r.expiresIn || 3600, r.email || email);
  }

  async resume(refreshToken) { this.refreshToken = refreshToken; await this._refresh(); }

  async _refresh() {
    const r = await this._request("POST", `${this.tokenUrl}?key=${this.apiKey}`,
      { grant_type: "refresh_token", refresh_token: this.refreshToken }, { form: true, auth: false });
    this._setSession(r.id_token, r.refresh_token, r.user_id, r.expires_in || 3600);
  }

  async _token() {
    if (!this.idToken || Date.now() > this.expires) {
      if (!this.refreshToken) throw new SyncError("auth", "not signed in");
      await this._refresh();
    }
    return this.idToken;
  }

  _docName(collection, id) { return `${this.dbPath}/users/${this.uid}/${collection}/${id}`; }

  async commit(writes) {
    if (writes.length) await this._request("POST", `${this.fsRoot}/${this.dbPath}:commit`, { writes });
  }

  upsertWrite(collection, id, fields) {
    const f = {};
    for (const [k, v] of Object.entries(fields)) f[k] = k === "price" && v != null ? { doubleValue: Number(v) } : toValue(v);
    return { update: { name: this._docName(collection, id), fields: f },
      updateTransforms: [{ fieldPath: "synced_at", setToServerValue: "REQUEST_TIME" }] };
  }

  deleteWrite(collection, id) { return { delete: this._docName(collection, id) }; }

  async changedSince(collection, cursor) {
    const query = { from: [{ collectionId: collection }],
      orderBy: [{ field: { fieldPath: "synced_at" }, direction: "ASCENDING" }] };
    if (cursor) query.where = { fieldFilter: { field: { fieldPath: "synced_at" }, op: "GREATER_THAN", value: { timestampValue: cursor } } };
    const res = await this._request("POST", `${this.fsRoot}/${this.dbPath}/users/${this.uid}:runQuery`, { structuredQuery: query });
    const out = [];
    for (const row of res) {
      const doc = row.document;
      if (!doc) continue;
      const f = {};
      for (const [k, v] of Object.entries(doc.fields || {})) f[k] = fromValue(v);
      f.uid = doc.name.split("/").pop();
      out.push(f);
    }
    return out;
  }

  async get(collection, id) {
    let doc;
    try {
      doc = await this._request("GET", `${this.fsRoot}/${this._docName(collection, id)}`);
    } catch (e) {
      if (e.code === "not_found") return null;
      throw e;
    }
    const f = {};
    for (const [k, v] of Object.entries(doc.fields || {})) f[k] = fromValue(v);
    return f;
  }

  /** Kullanıcı klasörü dışındaki bir belge (ör. "guncelleme/telefon"); yoksa null. */
  async getDoc(path) {
    let doc;
    try {
      doc = await this._request("GET", `${this.fsRoot}/${this.dbPath}/${path}`);
    } catch (e) {
      if (e.code === "not_found") return null;
      throw e;
    }
    const f = {};
    for (const [k, v] of Object.entries(doc.fields || {})) f[k] = fromValue(v);
    return f;
  }
}

/** Fotoğrafı buluta uygun boyutta JPEG'e çevirir (Firestore belge sınırı 1 MB). */
async function shrinkPhoto(blob, maxSide, maxBytes) {
  maxSide = maxSide || PHOTO_MAX_SIDE;
  maxBytes = maxBytes || MAX_PHOTO_BYTES;
  const head = new Uint8Array(await blob.slice(0, 3).arrayBuffer());
  if (blob.size <= maxBytes && head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff && maxSide === PHOTO_MAX_SIDE) {
    const bmp0 = await createImageBitmap(blob);
    const ok = Math.max(bmp0.width, bmp0.height) <= maxSide;
    bmp0.close();
    if (ok) return blob;
  }
  let bmp;
  try { bmp = await createImageBitmap(blob, { imageOrientation: "from-image" }); } catch (e) { return null; }
  let side = maxSide;
  try {
    for (;;) {
      const scale = Math.min(1, side / Math.max(bmp.width, bmp.height));
      const w = Math.max(1, Math.round(bmp.width * scale)), h = Math.max(1, Math.round(bmp.height * scale));
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
      g.drawImage(bmp, 0, 0, w, h);
      for (const q of [0.85, 0.75, 0.65, 0.55]) {
        const out = await new Promise(res => c.toBlob(res, "image/jpeg", q));
        if (out && out.size <= maxBytes) return out;
      }
      side = Math.floor(side * 0.75);
    }
  } finally { bmp.close(); }
}

/** Tam eşitleme: önce al, sonra gönder, sonra fotoğraflar. {received, sent} döndürür. */
async function syncAll(store, client, say) {
  say = say || (() => {});
  let received = 0, sent = 0;
  for (const table of SYNC_TABLES) {
    say("pull", table);
    const cursor = store.get(`sync_cursor_${table}`, null);
    const docs = await client.changedSince(table, cursor);
    if (docs.length) {
      received += await store.applyRemote(table, docs);
      let newest = null;
      for (const d of docs) if (d.synced_at && (!newest || tsKey(d.synced_at) > tsKey(newest))) newest = d.synced_at;
      if (newest && tsKey(newest) > tsKey(cursor)) await store.set(`sync_cursor_${table}`, newest);
    }
  }
  const dirty = store.dirtyRecords();
  for (const table of SYNC_TABLES) {
    const recs = dirty[table];
    for (let i = 0; i < recs.length; i += 200) {
      const chunk = recs.slice(i, i + 200);
      say("push", table);
      await client.commit(chunk.map(r => {
        const { uid, ...fields } = r;
        return client.upsertWrite(table, uid, fields);
      }));
      for (const r of chunk) await store.markClean(table, r.uid, r.mtime);
      sent += chunk.length;
    }
  }
  for (const name of store.photosToDelete()) {
    try { await client.commit([client.deleteWrite("photos", name)]); } catch (e) { if (e.code !== "not_found") throw e; }
    await store.setPhotoState(name, null);
  }
  for (const [name, itemUid] of store.photosToUpload()) {
    const blob = await store.photoBlob(name);
    if (!blob) continue;
    say("photo_up", name);
    const data = await shrinkPhoto(blob);
    if (!data) { await store.setPhotoState(name, "bad"); continue; }
    await client.commit([client.upsertWrite("photos", name, { data: new Bytes(await blobToBase64(data)), item: itemUid })]);
    await store.setPhotoState(name, "up");
  }
  for (const name of await store.missingPhotos()) {
    say("photo_down", name);
    const doc = await client.get("photos", name);
    if (doc && doc.data instanceof Bytes) {
      const blob = base64ToBlob(doc.data.b64);
      const thumb = await shrinkPhoto(blob, 320, 60000).catch(() => null);
      await store._put("photos", [{ name, blob }]);
      if (thumb) await store._put("thumbs", [{ name, blob: thumb }]);
      await store.setPhotoState(name, "up");
    }
  }
  if (received || sent) store.changed("sync");
  return { received, sent };
}

function syncErrorText(e) {
  const msg = (e.detail || "").toUpperCase();
  if (e.code === "config") return t("Firebase ayarları okunamadı. Konsoldaki firebaseConfig bölümünü olduğu gibi yapıştırın.");
  if (e.code === "network") return t("İnternete ya da Firebase'e bağlanılamadı.");
  if (msg.includes("EMAIL_EXISTS")) return t("Bu e-posta ile zaten bir hesap var. „Giriş yap“ı kullanın.");
  if (msg.includes("WEAK_PASSWORD")) return t("Şifre en az 6 karakter olmalı.");
  if (msg.includes("INVALID") || msg.includes("EMAIL_NOT_FOUND") || msg.includes("PASSWORD")) return t("E-posta ya da şifre hatalı.");
  if (msg.includes("OPERATION_NOT_ALLOWED") || msg.includes("CONFIGURATION_NOT_FOUND"))
    return t("Firebase'de e-posta/şifre ile giriş açılmamış (Authentication › Sign-in method).");
  if (msg.includes("PERMISSION") || e.code === "auth") return t("Firebase izin vermedi. Firestore kurallarını talimattaki gibi ayarlayın.");
  if (msg.includes("NOT_FOUND") || msg.includes("DATABASE")) return t("Firestore veritabanı bulunamadı. Firebase'de Firestore Database oluşturun.");
  return t("Eşitleme hatası: {m}", { m: e.detail || e.code || String(e) });
}

/** Hesap bilgilerini saklar, eşitlemeyi çalıştırır. */
const Cloud = {
  busy: false,
  lastError: "",
  listeners: [],
  timer: null,

  config() {
    try {
      let raw = Store.get("fb_config") || DEFAULT_FB_CONFIG;
      if (!raw && Store.get("fb_refresh")) {        // eski ortak projeden geçiş (bir kez)
        if (sha256Hex(String(Store.get("fb_email", "") || "").trim().toLowerCase()) === YONETICI_SHA256) { raw = ESKI_ORTAK_FB; Store.set("fb_config", raw); }
        else { Store.set("fb_refresh", null); Store.set("fb_ortak_kesildi", "1"); }
      }
      return raw ? parseConfig(raw) : null;
    } catch (e) { return null; }
  },
  isConnected() { return !!(this.config() && Store.get("fb_refresh")); },
  email() { return Store.get("fb_email", ""); },
  emit() { for (const f of this.listeners) f(this.statusText()); },

  statusText() {
    if (!this.isConnected()) return Store.get("fb_ortak_kesildi") === "1"
      ? t("Artık herkes kendi ücretsiz Firebase hesabını kullanıyor. Bulut hesabı bölümünden kendi hesabınızı bağlayın.")
      : t("Bulut hesabı bağlı değil");
    if (this.busy) return t("Eşitleniyor…");
    if (this.lastError) return "⚠ " + this.lastError;
    const last = Store.get("sync_last");
    return last ? t("Son eşitleme: {d}", { d: last }) : t("Henüz eşitlenmedi");
  },

  async connect(configText, email, password, create) {
    const config = parseConfig(configText);
    const c = new FirebaseClient(config);
    await c.signIn(email.trim(), password, create);
    if (Store.get("fb_uid") !== c.uid) await Store.resetSyncState();
    await Store.set("fb_config", configText.trim());
    await Store.set("fb_email", c.email || email.trim());
    await Store.set("fb_refresh", c.refreshToken);
    await Store.set("fb_uid", c.uid);
    this.lastError = "";
    this.emit();
  },

  async disconnect() {
    await Store.set("fb_refresh", null);
    await Store.set("fb_email", null);
    this.emit();
  },

  async syncNow() {
    if (!this.isConnected() || this.busy) return null;
    this.busy = true;
    this.emit();
    let result = null, netFail = false;
    try {
      const c = new FirebaseClient(this.config());
      await c.resume(Store.get("fb_refresh"));
      result = await syncAll(Store, c);
      if (c.refreshToken) await Store.set("fb_refresh", c.refreshToken);
      const d = new Date();
      await Store.set("sync_last", `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`);
      this.lastError = "";
    } catch (e) {
      this.lastError = e instanceof SyncError ? syncErrorText(e) : t("Eşitleme hatası: {m}", { m: String(e) });
      netFail = e instanceof SyncError && e.code === "network";
    } finally {
      this.busy = false;
      this.emit();
    }
    // internet yok: daha önce eşleşilen bilgisayar aynı ağdaysa onunla sessizce eşitle (v.1.0.8)
    if (netFail && typeof Lan !== "undefined" && Lan.peer() && Lan.available()) Lan.run({ quiet: true });
    return result;
  },

  /** Değişiklikten kısa süre sonra kendiliğinden eşitle */
  soon(ms) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.syncNow(), ms || 4000);
  },
};
