/* Organizer — v.1.0.8 eklentileri (telefon): yerel ağ eşitlemesi, sesli arama, geri al, çöp kutusu,
 * alışveriş listesi, ödünç takibi, usta iş geçmişi, koyu görünüm, admin ile iletişim. */
"use strict";

/* Yöneticinin adresi programda görünmez; mesaj FormSubmit üzerinden doğrudan iletilir. */
const adminEmail = () => atob("").split("").reverse().join("");

// ====================================================================== Android kabuğu ile eşzamansız çağrılar (kabuk 3)
const NativeCall = {
  seq: 0, pending: new Map(),
  has(name) { return !!(Native && typeof Native[name] === "function"); },
  /** Native[name](id, ...args) çağırır; Java işini bitirince window.__nativeCb(id, ok, base64) ile döner. */
  call(name, ...args) {
    return new Promise((resolve, reject) => {
      const id = ++this.seq;
      this.pending.set(id, { resolve, reject });
      try { Native[name](id, ...args); } catch (e) { this.pending.delete(id); reject(e); }
    });
  },
};
function b64ToText(b64) {
  if (!b64) return "";
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}
function textToB64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
window.__nativeCb = (id, ok, b64) => {
  const p = NativeCall.pending.get(id);
  if (!p) return;
  NativeCall.pending.delete(id);
  const text = b64ToText(b64);
  if (ok) p.resolve(text); else p.reject(new Error(text || "native"));
};

function fmtDay(v) {
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(v || "");
  return m ? `${m[3]}.${m[2]}.${m[1]}` : (v || "");
}
function loanText(d) {
  if (!d.loan_to) return "";
  let s = "🤝 " + d.loan_to;
  if (d.loan_date) s += " · " + fmtDay(d.loan_date);
  if (d.loan_due) {
    s += " → " + fmtDay(d.loan_due);
    const late = overdueDays(d);
    if (late > 0) s += "  " + t("({n} gün gecikti)", { n: late });
  }
  return s;
}

// ====================================================================== geri al
const Undo = {
  stack: [],
  remember(label, uids, key) {
    const top = this.stack[this.stack.length - 1];
    if (key && top && top.key === key) return;
    this.stack.push({ label, snap: Store.snapshot(uids), key });
    if (this.stack.length > 30) this.stack.shift();
  },
  async undo() {
    const e = this.stack.pop();
    if (!e) return;
    await Store.restoreSnapshot(e.snap);
    Cloud.soon();
    toast(t("↶ Geri alındı: {x}", { x: e.label }));
    App.render(true);
  },
  /** İşlemden sonra "Geri al" düğmeli bildirim */
  offer(text) { toast(text, [t("↶  Geri al"), () => this.undo()]); },
};

// ====================================================================== görünüm (açık / koyu)
const Theme = {
  mode() { return Store.get("theme", "light"); },
  dark() {
    const m = this.mode();
    if (m === "dark") return true;
    if (m === "light") return false;
    if (NativeCall.has("isNight")) return !!Native.isNight();
    return !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  },
  apply() {
    const dark = this.dark();
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark ? "#0f1c21" : "#1d5f74";
    if (NativeCall.has("setDark")) { try { Native.setDark(dark); } catch (e) { /* eski kabuk */ } }
  },
  async set(mode) { await Store.set("theme", mode); this.apply(); App.render(true); },
};

// ====================================================================== sesli arama
const Voice = {
  available() { return NativeCall.has("listen") || !!(window.SpeechRecognition || window.webkitSpeechRecognition); },
  lang() { return { tr: "tr-TR", en: "en-US", ar: "ar-SY" }[I18N.lang] || "tr-TR"; },
  async listen() {
    if (NativeCall.has("listen")) return NativeCall.call("listen", this.lang());
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) throw new Error("voice");
    return new Promise((resolve, reject) => {
      const r = new SR();
      r.lang = this.lang();
      r.onresult = e => resolve(e.results[0][0].transcript);
      r.onerror = e => reject(new Error(e.error || "voice"));
      r.start();
    });
  },
  speak(text) {
    if (NativeCall.has("speak")) { try { Native.speak(text, this.lang()); } catch (e) { /* yok */ } }
    else if (window.speechSynthesis) { const u = new SpeechSynthesisUtterance(text); u.lang = this.lang(); speechSynthesis.speak(u); }
  },
  /** Mikrofon düğmesi: konuş → ara ya da ekle */
  async start() {
    let text;
    try {
      toast(t("🎤 Dinliyorum… „Matkap nerede?“ ya da „3 ampul ekle“"));
      text = await this.listen();
    } catch (e) {
      toast(t("Ses anlaşılamadı. Yeniden deneyin."));
      return;
    }
    if (!text) return;
    const cmd = parseVoice(text);
    if (cmd.intent === "add" && cmd.query) { voiceAdd(cmd); return; }
    ItemsPage.search = text;
    App.tab = 0;
    App.render();
    if (cmd.intent === "where") {
      const found = ItemsPage.items();
      if (!found.length) this.speak(t("„{x}“ bulunamadı.", { x: cmd.query }));
      else this.speak(found.slice(0, 2).map(d => `${d.name}: ${d.location_path || t("yeri belirtilmemiş")}`).join(". "));
    }
  },
};

/** "3 ampul ekle" → yeni eşya formu; söylenen yer adı varsa o yer seçilir */
function voiceAdd(cmd) {
  let name = cmd.query, location = ItemsPage.loc || "";
  const low = norm(name);
  for (const n of Store.treeOrdered("locations")) {
    if (n.name.length > 2 && low.includes(norm(n.name))) {
      location = n.uid;
      name = name.replace(new RegExp(n.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"), "").trim() || cmd.query;
    }
  }
  itemForm(null, null, { name: name.charAt(0).toLocaleUpperCase(numLocale()) + name.slice(1), quantity: cmd.qty || 1, location });
}

/** Arama kutusundaki soruya cevap kartı ("Matkap nerede?") */
function answerCard(search, items) {
  if (!search.trim()) return null;
  const cmd = parseVoice(search);
  if (cmd.intent === "search" || !cmd.query) return null;
  if (cmd.intent === "add") {
    return el("div.answer", null, [el("span", { text: t("🎤 Yeni eşya: {x}", { x: (cmd.qty ? cmd.qty + " × " : "") + cmd.query }) }),
      el("button.btn.primary", { text: t("＋ Ekle"), onclick: () => { ItemsPage.search = ""; voiceAdd(cmd); } })]);
  }
  if (!items.length) return el("div.answer", { text: t("🎤 „{x}“ bulunamadı.", { x: cmd.query }) });
  return el("div.answer", null, items.slice(0, 3).map(d => el("div", null, [el("b", { text: d.name }),
    " → 📍 " + (d.location_path || t("yeri belirtilmemiş")) + (d.loan_to ? "  ·  " + loanText(d) : "")])));
}

// ====================================================================== yerel ağ eşitlemesi (internetsiz)
const LAN_PORT = 47321;
const Lan = {
  busy: false, lastError: "",
  available() { return NativeCall.has("lanPost") || location.protocol === "http:"; },
  peer() { return Store.get("lan_peer", ""); },
  status() {
    if (this.busy) return t("Eşitleniyor…");
    if (this.lastError) return "⚠ " + this.lastError;
    const last = Store.get("lan_last", "");
    return last ? t("Son yerel ağ eşitlemesi: {d}", { d: last }) : t("Henüz yerel ağda eşitlenmedi");
  },
  async discover() {
    if (NativeCall.has("lanDiscover")) {
      try { return JSON.parse(await NativeCall.call("lanDiscover")) || []; } catch (e) { return []; }
    }
    return [];
  },
  async post(host, port, path, body) {
    const url = `http://${host}:${port || LAN_PORT}${path}`;
    let status, text;
    if (NativeCall.has("lanPost")) {
      const raw = await NativeCall.call("lanPost", url, textToB64(JSON.stringify(body)));
      const i = raw.indexOf("\n");
      status = parseInt(raw.slice(0, i), 10);
      text = raw.slice(i + 1);
    } else {
      let r;
      try { r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
      catch (e) { status = 0; text = String(e); }
      if (r) { status = r.status; text = await r.text(); }
    }
    if (status === 401) throw new SyncError("key");
    if (!status) throw new SyncError("network", text);
    if (status >= 400) throw new SyncError("server", text);
    return text ? JSON.parse(text) : {};
  },
  /** Bilgisayarla eşitle: kayıtları gönder/al, eksik fotoğrafları gönder/al. */
  async syncWith(host, port, key) {
    const refs = new Map(Store.allPhotos());
    const have = [];
    for (const p of refs.keys()) if (await Store.hasPhoto(p)) have.push(p);
    const res = await this.post(host, port, "/organizer/lan/sync",
      { key, device: t("Telefon"), records: Store.allRecords(), have });
    let received = 0;
    for (const table of SYNC_TABLES) {
      const recs = ((res.records || {})[table] || []).filter(r => r && r.uid);
      if (recs.length) received += await Store.applyRemote(table, recs, true);
    }
    let sent = 0, photos = 0;
    for (const name of res.need || []) {
      const blob = await Store.photoBlob(name);
      if (!blob) continue;
      await this.post(host, port, "/organizer/lan/upload", { key, name, data: await blobToBase64(blob) });
      sent++;
    }
    const theirs = new Set(res.have || []);
    for (const [name] of Store.allPhotos()) {
      if (!theirs.has(name) || await Store.hasPhoto(name)) continue;
      const r = await this.post(host, port, "/organizer/lan/photo", { key, name });
      if (!r.data) continue;
      const blob = base64ToBlob(r.data);
      const thumb = await shrinkPhoto(blob, 320, 60000).catch(() => null);
      await Store._put("photos", [{ name, blob }]);
      if (thumb) await Store._put("thumbs", [{ name, blob: thumb }]);
      photos++;
    }
    const d = new Date();
    await Store.set("lan_last", `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())} · ${res.name || host}`);
    Store.changed("sync");
    return { received, sent, photos, name: res.name || host };
  },
  keyFor(host) {
    return Store.get("lan_key_" + host, "") || (Store.get("fb_uid") ? lanUidKey(Store.get("fb_uid")) : "");
  },
  /** quiet: sessizce dene (internet yokken kendiliğinden); kod gerekirse sorar */
  async run({ host, port, name, quiet } = {}) {
    if (this.busy) return null;
    if (!host) {
      const peer = this.peer();
      if (!peer) return quiet ? null : this.findAndSync();
      [host, port] = peer.split(":");
      name = Store.get("lan_peer_name", host);
    }
    port = parseInt(port, 10) || LAN_PORT;
    let key = await this.keyFor(host);
    this.busy = true; this.lastError = ""; App.syncState(Cloud.statusText());
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        if (!key) {
          if (quiet) return null;
          key = await ask(t("{name} bilgisayarının Ayarlar → Yerel ağ eşitlemesi bölümündeki 6 haneli kodu yazın:", { name }),
            { input: true, placeholder: "123456", yes: t("Eşitle") });
          if (!key) return null;
          key = key.replace(/\D/g, "");
        }
        try {
          const r = await this.syncWith(host, port, key);
          await Store.set("lan_key_" + host, key);
          await Store.set("lan_peer", `${host}:${port}`);
          await Store.set("lan_peer_name", name || host);
          if (!quiet) toast(t("{name} ile eşitlendi · {a} kayıt alındı · {b} fotoğraf gönderildi · {c} fotoğraf alındı",
            { name: r.name, a: r.received, b: r.sent, c: r.photos }));
          return r;
        } catch (e) {
          if (e.code === "key") { await Store.set("lan_key_" + host, null); key = ""; if (quiet) return null; toast(t("Kod yanlış ya da değişmiş.")); continue; }
          throw e;
        }
      }
    } catch (e) {
      this.lastError = e.code === "network" ? t("{name} bilgisayarına ulaşılamadı. Aynı Wi-Fi'de ve Organizer açık mı?", { name: name || host })
        : t("Eşitleme hatası: {m}", { m: e.detail || e.message || String(e) });
      if (!quiet) toast(this.lastError);
    } finally {
      this.busy = false;
      App.syncState(Cloud.statusText());
      if (SettingsPage.lanDraw) SettingsPage.lanDraw();
    }
    return null;
  },
  async findAndSync() {
    toast(t("Ağdaki bilgisayarlar aranıyor…"));
    const found = await this.discover();
    if (!found.length) return this.manual(t("Aynı ağda açık bir Organizer bilgisayarı bulunamadı."));
    if (found.length === 1) return this.run(found[0]);
    return new Promise(res => menu(t("Hangi bilgisayarla eşitlensin?"),
      found.map(f => [`💻  ${f.name}  (${f.host})`, () => res(this.run(f))])));
  },
  async manual(msg) {
    const v = await ask((msg ? msg + "\n\n" : "") + t("Bilgisayarın adresini yazın (Organizer'ın Ayarlar sayfasında görünür, ör. 192.168.1.20):"),
      { input: true, value: (this.peer() || "").split(":")[0], placeholder: "192.168.1.20", yes: t("Eşitle") });
    if (!v) return null;
    const [host, port] = v.trim().split(":");
    return this.run({ host, port: port || LAN_PORT, name: host });
  },
};
async function lanUidKey(uid) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("organizer-lan:" + uid));
  return Array.from(new Uint8Array(buf), x => x.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

// ====================================================================== çöp kutusu
function trashPage() {
  fullPage({ title: t("🗑  Çöp kutusu"), onClose: () => App.render(true), build: () => {
    const box = el("div");
    const sel = new Set();
    const draw = () => {
      box.innerHTML = "";
      const items = Store.listItems({ sort: "trashed_desc", trashed: true });
      box.append(el("div.hint", { style: { marginBottom: "10px" },
        text: t("Silinen eşyalar fotoğraflarıyla birlikte {n} gün burada kalır, sonra kendiliğinden kalıcı olarak silinir.", { n: TRASH_DAYS }) }));
      if (!items.length) { box.append(el("div.empty", { text: t("Çöp kutusu boş.") })); return; }
      for (const d of items) {
        const left = Math.max(0, TRASH_DAYS - Math.floor((Date.now() - new Date(d.trashed_at)) / 86400000));
        const thumb = el("div.thumb", { text: "📦" });
        const ph = d.photos.find(p => !isReceipt(p));
        if (ph) PhotoCache.url(ph, true).then(u => { if (u) { thumb.textContent = ""; thumb.style.backgroundImage = `url("${u}")`; } });
        const card = el("div.card.item" + (sel.has(d.uid) ? ".sel" : ""), { onclick: () => { sel.has(d.uid) ? sel.delete(d.uid) : sel.add(d.uid); draw(); } }, [
          thumb, el("div.body", null, [el("div.name", { text: d.name }),
            el("div.meta", { text: [d.location_path ? "📍 " + d.location_path : "", t("Silindiği gün:") + " " + fmtDay(d.trashed_at.slice(0, 10)),
              t("{n} gün kaldı", { n: left })].filter(Boolean).join(" · ") })]),
          el("button.btn.primary", { text: t("↩"), title: t("↩  Geri yükle"), onclick: async e => {
            e.stopPropagation(); await Store.restoreItems([d.uid]); Cloud.soon(); toast(t("Geri yüklendi: {x}", { x: d.name })); draw(); } }),
        ]);
        box.append(card);
      }
      const ids = () => sel.size ? [...sel] : items.map(d => d.uid);
      box.append(el("div.hrow", { style: { marginTop: "12px" } }, [
        el("button.btn.primary.grow", { text: sel.size ? t("↩  Seçilenleri geri yükle ({n})", { n: sel.size }) : t("↩  Hepsini geri yükle"),
          onclick: async () => { await Store.restoreItems(ids()); sel.clear(); Cloud.soon(); draw(); } }),
        el("button.btn.danger.grow", { text: sel.size ? t("Kalıcı olarak sil ({n})", { n: sel.size }) : t("Çöp kutusunu boşalt"),
          onclick: async () => {
            const list = ids();
            if (await ask(t("{n} eşya kalıcı olarak silinsin mi? Bu işlem geri alınamaz.", { n: list.length }), { yes: t("Kalıcı olarak sil"), danger: true })) {
              await Store.purgeItems(list); sel.clear(); Cloud.soon(); draw();
            }
          } }),
      ]));
    };
    draw();
    return box;
  } });
}

// ====================================================================== alışveriş listesi
function shoppingText(items) {
  const d = new Date();
  const lines = [t("🛒 Alışveriş listesi") + ` — ${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`, ""];
  for (const x of items) {
    const need = isLow(x) ? Math.max(1, x.min_qty - x.quantity) : 1;
    lines.push(`☐ ${x.name} × ${need}` + (x.shop_name ? `  (${x.shop_name})` : ""));
  }
  return lines.join("\n");
}

function shoppingPage() {
  fullPage({ title: t("🛒  Alışveriş listesi"), onClose: () => App.render(true), build: () => {
    const box = el("div");
    const draw = () => {
      box.innerHTML = "";
      const items = Store.shoppingList();
      box.append(el("div.hint", { style: { marginBottom: "10px" }, text: t("Eşyanın „En az adet“ değeri girildiyse adedi bunun altına düşünce kendiliğinden buraya gelir. Başka eşyaları da elle ekleyebilirsiniz. Aldıktan sonra „✓ Alındı“ deyin; adet artar.") }));
      if (!items.length) box.append(el("div.empty", { text: t("Alışveriş listesi boş. ✓") }));
      for (const d of items) {
        const low = isLow(d);
        const need = low ? Math.max(1, d.min_qty - d.quantity) : 1;
        box.append(el("div.card.shoprow", null, [
          el("div.body", null, [
            el("div.name", { text: d.name }),
            el("div.meta", { text: [t("Var: {n}", { n: d.quantity }), low ? t("En az: {n}", { n: d.min_qty }) : t("Elle eklendi"),
              d.shop_name ? "🏪 " + d.shop_name : ""].filter(Boolean).join(" · ") }),
          ]),
          el("span.need", { text: "× " + need }),
          el("button.btn.primary", { text: t("✓  Alındı"), onclick: async () => {
            const v = await ask(t("„{name}“ kaç adet alındı?", { name: d.name }), { input: true, value: String(need), yes: t("✓  Alındı") });
            if (v === null) return;
            Undo.remember(t("„{name}“ alındı", { name: d.name }), [d.uid]);
            await Store.bought(d.uid, parseInt(v, 10) || 0); Cloud.soon(); draw();
          } }),
          el("button.more", { text: "⋮", onclick: () => menu(d.name, [
            d.to_buy ? [t("Listeden çıkar"), async () => { await Store.patchItems([d.uid], { to_buy: false }); Cloud.soon(); draw(); }] : null,
            low ? [t("Az kaldı uyarısını kapat"), async () => { await Store.patchItems([d.uid], { min_qty: 0, to_buy: false }); Cloud.soon(); draw(); }] : null,
            [t("Eşyayı aç"), () => itemDetail(d.uid)],
          ]) }),
        ]));
      }
      box.append(el("button.btn.block", { text: t("＋  Listeye eşya ekle"), onclick: () => {
        const cands = Store.listItems({ sort: "name_asc" }).filter(x => !x.to_buy && !isLow(x));
        sheet(t("＋  Listeye eşya ekle"), close => {
          const q = el("input.in", { type: "search", placeholder: t("Eşya ara…") });
          const list = el("div.menu");
          const fill = () => {
            list.innerHTML = "";
            const terms = norm(q.value).split(/\s+/).filter(Boolean);
            for (const x of cands.filter(x => terms.every(w => norm(x.name).includes(w))).slice(0, 60)) {
              list.append(el("button", { text: x.name + (x.location_path ? "  ·  " + x.location_path : ""), onclick: async () => {
                close(); await Store.patchItems([x.uid], { to_buy: true }); Cloud.soon(); draw(); } }));
            }
          };
          q.addEventListener("input", fill);
          fill();
          return el("div", null, [q, el("div", { style: { marginTop: "10px" } }, list)]);
        });
      } }));
      if (items.length) box.append(el("div.hrow", { style: { marginTop: "8px" } }, [
        el("button.btn.grow", { text: t("📋  Kopyala"), onclick: async () => { await copyText(shoppingText(items)); toast(t("Liste kopyalandı.")); } }),
        el("button.btn.grow", { text: t("WhatsApp ile gönder"), onclick: () => openUrl("https://wa.me/?text=" + encodeURIComponent(shoppingText(items))) }),
      ]));
    };
    draw();
    return box;
  } });
}

// ====================================================================== ödünç
function lendForm(uid, after) {
  const d = Store.t.items.get(uid);
  const to = el("input.in", { value: d.loan_to || "", placeholder: t("Örn. Komşu Ahmet") });
  const phone = el("input.in.ltr", { type: "tel", value: d.loan_phone || "", placeholder: t("(isteğe bağlı)") });
  const date = el("input.in", { type: "date", value: d.loan_date || todayStr() });
  const plus7 = new Date(Date.now() + 7 * 86400000);
  const due = el("input.in", { type: "date", value: d.loan_due || (d.loan_to ? "" : `${plus7.getFullYear()}-${pad(plus7.getMonth() + 1)}-${pad(plus7.getDate())}`) });
  const err = el("div.err");
  sheet(t("„{name}“ kime ödünç verildi?", { name: d.name }), close => {
    setTimeout(() => to.focus(), 80);
    return el("div", null, [
      el("label.f", { text: t("Kime:") }), to,
      el("label.f", { text: t("Telefonu:") }), phone,
      el("label.f", { text: t("Verildiği gün:") }), date,
      el("label.f", { text: t("Geri getireceği gün:") }), due,
      el("div.hint", { text: t("Dönüş günü geçince eşya listede kırmızı görünür. Geri gelince „↩ Geri geldi“ deyin; kayıt geçmişte kalır.") }),
      err,
      el("button.btn.primary.block", { text: t("Kaydet"), onclick: async () => {
        if (!to.value.trim()) { err.textContent = t("Lütfen bir ad yazın"); return; }
        Undo.remember(t("„{name}“ ödünç verildi", { name: d.name }), [uid]);
        await Store.lend(uid, to.value, phone.value, date.value, due.value);
        Cloud.soon(); close(); if (after) after();
      } }),
    ]);
  });
}

async function giveBack(uid, after) {
  const d = Store.t.items.get(uid);
  if (!(await ask(t("„{name}“ {who} kişisinden geri geldi mi?", { name: d.name, who: d.loan_to }), { yes: t("↩  Geri geldi") }))) return;
  Undo.remember(t("„{name}“ geri geldi", { name: d.name }), [uid]);
  await Store.giveBack(uid);
  Cloud.soon();
  if (after) after();
}

// ====================================================================== usta iş geçmişi
function jobsSummary(jobs) {
  if (!jobs || !jobs.length) return "";
  const tot = {};
  for (const j of jobs) if (j.cost != null && j.cost !== "") tot[j.currency || "USD"] = (tot[j.currency || "USD"] || 0) + Number(j.cost);
  const parts = CURRENCIES.filter(([c]) => c in tot).map(([c]) => fmtPrice(tot[c], c));
  return t("{n} iş", { n: jobs.length }) + (parts.length ? " · " + parts.join(" + ") : "");
}

/** Usta formunda: işler listesi (düzenlenebilir). value() güncel listeyi verir. */
function jobsEditor(initial) {
  const jobs = (initial || []).map(j => ({ ...j })).sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  const box = el("div");
  const sum = el("div.hint");
  const draw = () => {
    box.innerHTML = "";
    sum.textContent = jobsSummary(jobs) || t("Henüz iş kaydı yok");
    jobs.forEach((j, i) => box.append(el("div.jobrow", { onclick: () => edit(i) }, [
      el("span.jd", { text: fmtDay(j.date) }),
      el("span.jw", { text: j.work + (j.notes ? "\n" + j.notes : "") }),
      el("span.jc", { text: j.cost != null && j.cost !== "" ? fmtPrice(Number(j.cost), j.currency) : "—" }),
    ])));
  };
  const edit = i => {
    const j = i == null ? { date: todayStr(), work: "", cost: null, currency: Store.get("default_currency", "USD"), notes: "" } : jobs[i];
    const date = el("input.in", { type: "date", value: j.date || todayStr() });
    const work = el("input.in", { value: j.work || "", placeholder: t("Örn. Mutfak musluğu değişti") });
    const cost = el("input.in.grow", { type: "number", inputmode: "decimal", step: "0.01", min: 0, value: j.cost == null ? "" : j.cost, placeholder: "0.00" });
    const cur = el("select.in", { style: { width: "auto" } }, CURRENCIES.map(([c, sym, n]) => el("option", { value: c, text: `${sym}  ${t(n)}` })));
    cur.value = j.currency || "USD";
    const notes = el("textarea.in", { style: { minHeight: "60px" } });
    notes.value = j.notes || "";
    sheet(i == null ? t("Yeni iş / ödeme") : t("İşi düzenle"), close => el("div", null, [
      el("label.f", { text: t("Tarih:") }), date,
      el("label.f", { text: t("Yapılan iş:") }), work,
      el("label.f", { text: t("Ödenen ücret:") }), el("div.hrow", null, [cost, cur]),
      el("label.f", { text: t("Notlar:") }), notes,
      el("button.btn.primary.block", { text: t("Kaydet"), onclick: () => {
        if (!work.value.trim()) { work.focus(); return; }
        const v = { id: j.id || newUid().slice(0, 12), date: date.value, work: work.value.trim(),
          cost: cost.value === "" ? null : Number(cost.value), currency: cur.value, notes: notes.value.trim() };
        if (i == null) jobs.unshift(v); else jobs[i] = v;
        jobs.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
        close(); draw();
      } }),
      i != null ? el("button.btn.danger.block", { text: t("Sil"), onclick: () => { jobs.splice(i, 1); close(); draw(); } }) : null,
    ]));
  };
  draw();
  return {
    node: el("div", null, [el("div.formsec", { text: t("🧾  Yapılan işler ve ödemeler") }), sum, box,
      el("button.btn.block", { text: t("＋ İş ekle"), onclick: () => edit(null) })]),
    value: () => jobs,
  };
}

// ====================================================================== admin ile iletişim
/** FormSubmit'e gönderir → "ok" | "activation" (yönetici formu henüz etkinleştirmedi) | "fail". */
async function feedbackPost(body) {
  try {
    const r = await fetch("https://formsubmit.co/ajax/" + adminEmail(), { method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (String(j.success) === "true") return "ok";
    return /activat/i.test(j.message || "") ? "activation" : "fail";
  } catch (x) { return "fail"; }
}

/** Gönderilemeyen mesajlar kaybolmaz: burada bekler, bağlantı gelince kendiliğinden gönderilir. */
const Outbox = {
  KEY: "admin_outbox",
  list() { try { return JSON.parse(localStorage.getItem(this.KEY) || "[]"); } catch (e) { return []; } },
  save(a) { try { if (a.length) localStorage.setItem(this.KEY, JSON.stringify(a.slice(-50))); else localStorage.removeItem(this.KEY); } catch (e) { /* yok */ } },
  add(b) { const a = this.list(); a.push(b); this.save(a); },
  busy: false,
  async flush() {
    if (this.busy) return; const box = this.list(); if (!box.length) return;
    this.busy = true; const sent = [];
    for (const b of box) { if (await feedbackPost(b) === "ok") sent.push(JSON.stringify(b)); else break; }
    if (sent.length) this.save(this.list().filter(b => !sent.includes(JSON.stringify(b))));
    this.busy = false;
  },
  init() {
    setTimeout(() => this.flush(), 20000);
    setInterval(() => this.flush(), 15 * 60 * 1000);
    window.addEventListener("online", () => setTimeout(() => this.flush(), 3000));
  },
};
Outbox.init();

function feedbackPage() {
  const kinds = ["💡 Öneri / istek", "🐞 Hata bildirimi", "❓ Soru", "💬 Diğer"];
  const kind = el("select.in", null, kinds.map(k => el("option", { value: k, text: t(k) })));
  const who = el("input.in", { placeholder: t("(isteğe bağlı) adınız, telefonunuz ya da e-postanız") });
  const msg = el("textarea.in", { placeholder: t("Mesajınız…"), style: { minHeight: "160px" } });
  const subject = () => `Organizer ${goster()} — ${t(kind.value)}`;
  const body = () => [msg.value.trim(), "", "—", who.value.trim() ? t("Size ulaşma:") + " " + who.value.trim() : "",
    `Organizer ${goster()} · ${t("Telefon")} · ${navigator.userAgent.replace(/^.*?\(([^)]*)\).*$/, "$1")}`].filter(x => x !== "").join("\n");
  const ready = () => { if (!msg.value.trim()) { msg.focus(); toast(t("Lütfen mesajınızı yazın.")); return false; } return true; };
  let busy = false;
  const sendBtn = el("button.btn.primary.block", { text: t("✉  Gönder"), onclick: async () => {
    if (busy || !ready()) return;
    const c = who.value.trim();
    const body = { _subject: "Organizer: " + t(kind.value), _template: "table", _captcha: "false", Konu: t(kind.value),
      Ulasma: c || "-", Mesaj: msg.value.trim().slice(0, 5000), Surum: goster(), Cihaz: "Android", Dil: I18N.lang };
    const m = /[^@\s]+@[^@\s]+\.[^@\s]+/.exec(c);
    if (m) { body.email = m[0]; body._replyto = m[0]; }
    body.Tarih = new Date().toLocaleString("tr-TR");
    busy = true; sendBtn.disabled = true;
    const res = await feedbackPost(body);
    if (res === "ok") { msg.value = ""; toast(t("Mesajınız yöneticiye iletildi. Teşekkürler!")); }
    else { Outbox.add(body); msg.value = ""; toast(t("Mesajınız kaydedildi; bağlantı kurulunca program kendiliğinden yöneticiye gönderecek. Teşekkürler!")); }
    busy = false; sendBtn.disabled = false;
  } });
  fullPage({ title: t("✉  Admin ile iletişime geç"), build: () => el("div", null, [
    el("div.hint", { text: t("Öneri, istek ya da hata bildirimlerinizi yazın. Programın geliştirilmesi için doğrudan geliştiriciye gider.") }),
    el("label.f", { text: t("Konu:") }), kind,
    el("label.f", { text: t("Size ulaşma:") }), who,
    el("label.f", { text: t("Mesajınız…").replace("…", ":") }), msg,
    sendBtn,
    el("button.btn.block", { text: t("✉  E-posta uygulamasıyla gönder"), onclick: () => {
      if (ready()) openUrl(`mailto:${adminEmail()}?subject=${encodeURIComponent(subject())}&body=${encodeURIComponent(body())}`); } }),
    el("button.btn.block", { text: t("Gmail ile gönder (tarayıcı)"), onclick: () => {
      if (ready()) openUrl(`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(adminEmail())}&su=${encodeURIComponent(subject())}&body=${encodeURIComponent(body())}`); } }),
    el("button.btn.block", { text: t("📋  Kopyala"), onclick: async () => {
      if (ready()) { await copyText(`${subject()}\n\n${body()}`); toast(t("Mesaj kopyalandı.")); } } }),
  ]) });
}
