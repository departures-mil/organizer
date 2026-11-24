/* Organizer — telefon arayüzü. Masaüstündeki bütün özellikler: eşyalar (fotoğraf, adet, kategori, yer, fiyat,
 * tarih, not), sınıflandırma ağaçları, arama, sıralama, toplu taşıma/silme, ustalar ve dükkanlar, ayarlar, yedek, bulut. */
"use strict";

const APP_VERSION = "2.2.1";   // semver (2.2.0'dan beri ekranda da aynı); eski 2.1.0.x güncelleyicileri bunu "daha yeni" görür
function goster(v) {
  const p = String(v === undefined ? APP_VERSION : (v || "")).trim().split(".").filter(x => x !== "");
  if (!p.length) return "";
  if (p.length === 4 && p[0] === "2") p.shift();
  return "v." + p.join(".");
}
const Native = window.Native || null;   // Android kabuğunun sağladığı köprü (kopyala, paylaş, bağlantı aç)
const $ = (sel, root) => (root || document).querySelector(sel);

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Küçük DOM oluşturucu: el("div.card", {onclick}, [çocuklar]) */
function el(spec, attrs, kids) {
  const [tag, ...classes] = spec.split(".");
  const e = document.createElement(tag || "div");
  if (classes.length) e.className = classes.join(" ");
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "html") e.innerHTML = v;
      else if (k === "text") e.textContent = v;
      else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
      else if (k in e && typeof v !== "string") e[k] = v;
      else e.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const k of [].concat(kids || [])) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
}

function numLocale() { return I18N.lang === "tr" ? "tr-TR" : "en-US"; }

function fmtNum(n, frac) {
  return new Intl.NumberFormat(numLocale(), { minimumFractionDigits: frac || 0, maximumFractionDigits: frac || 0 }).format(n);
}

let PRICES_HIDDEN = false;   // üst çubuktaki göz düğmesi: fiyatlar •••• olarak görünür
function fmtPrice(price, cur) {
  if (price == null) return "—";
  if (PRICES_HIDDEN) return "••••••";
  const s = fmtNum(price, 2);
  return cur === "USD" ? `$${s}` : cur === "SYP" ? `${s} SYP` : `${s} ₺`;
}
/** Fiyatın kaynağı: ⚡ otomatik (tahmini, kontrol edilmedi) · ✎ kullanıcının girdiği */
const isAutoPrice = d => d.price != null && !!d.price_auto;
function priceMark(d) { return d.price == null ? "" : (isAutoPrice(d) ? "⚡ " : "✎ "); }
async function setAutoPrice(uids, on) {
  const list = uids.filter(u => { const d = Store.t.items.get(u); return d && d.price != null; });
  if (!list.length) return;
  Undo.remember(t("Fiyat işareti değişti"), list);
  await Store.updateItems(list, "price_auto", !!on);
  Cloud.soon();
  toast(on ? t("⚡ Otomatik fiyat olarak işaretlendi") : t("✎ Fiyat onaylandı"));
}

function fmtDate(v) {
  const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(v || "");
  return m ? `${m[3]}.${m[2]}.${m[1]}  ${m[4]}:${m[5]}` : (v || "");
}

let toastTimer;
/** action: [düğme yazısı, fn] — ör. "↶ Geri al" */
function toast(text, action) {
  const tEl = $("#toast");
  tEl.textContent = text;
  tEl.classList.toggle("act", !!action);
  if (action) tEl.append(el("button", { text: action[0], onclick: () => { tEl.classList.remove("show"); action[1](); } }));
  tEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => tEl.classList.remove("show"), action ? 6000 : 2600);
}

function openUrl(url) {
  if (Native && Native.openUrl) Native.openUrl(url);
  else window.open(url, "_blank");
}

async function copyText(text) {
  if (Native && Native.copy) { Native.copy(text); return; }
  try { await navigator.clipboard.writeText(text); } catch (e) { /* desteklenmiyor */ }
}

// ====================================================================== katmanlar
const Layers = {
  stack: [],
  push(node, onClose) {
    const layer = el("div.layer", null, node);
    $("#layers").append(layer);
    const entry = { layer, onClose };
    this.stack.push(entry);
    return () => this.close(entry);
  },
  close(entry) {
    const i = this.stack.indexOf(entry || this.stack[this.stack.length - 1]);
    if (i < 0) return false;
    const [e] = this.stack.splice(i, 1);
    e.layer.remove();
    if (e.onClose) e.onClose();
    return true;
  },
  top() { return this.stack.length; },
};

/** Alt panel. content: düğüm ya da (kapat) => düğüm */
function sheet(title, build) {
  let close;
  const box = el("div.sheet", null, [el("div.grip"), title ? el("h3", { text: title }) : null]);
  const node = el("div", null, [el("div.shade", { onclick: () => close() }), box]);
  close = Layers.push(node);
  box.append(build(close));
  return close;
}

/** Tam ekran sayfa: { title, save: [etiket, fn], build(close, bar) } */
function fullPage({ title, saveLabel, onSave, build, onClose }) {
  let close;
  const content = el("div.content");
  const bar = el("div.bar", null, [
    el("button", { text: "✕", "aria-label": t("Kapat"), onclick: () => close() }),
    el("h2", { text: title }),
    onSave ? el("button.save", { text: saveLabel || t("Kaydet"), onclick: () => onSave(close) }) : null,
  ]);
  const node = el("div.full", null, [bar, content]);
  close = Layers.push(node, onClose);
  content.append(build(close, bar));
  return close;
}

function ask(message, { yes, no, danger, input, value, placeholder } = {}) {
  return new Promise(resolve => {
    let close, done = false;
    const inp = input ? el("input.in", { value: value || "", placeholder: placeholder || "" }) : null;
    const finish = v => { if (!done) { done = true; close(); resolve(v); } };
    const box = el("div.dialog", null, [
      el("div.msg", { text: message }),
      inp ? el("div", { style: { marginBottom: "14px" } }, inp) : null,
      el("div.btns", null, [
        no === false ? null : el("button.btn", { text: no || t("Vazgeç"), onclick: () => finish(input ? null : false) }),
        el("button.btn." + (danger ? "danger" : "primary"), { text: yes || t("Tamam"),
          onclick: () => finish(input ? inp.value.trim() || null : true) }),
      ]),
    ]);
    close = Layers.push(el("div", null, [el("div.shade", { onclick: () => finish(input ? null : false) }), box]),
      () => { if (!done) { done = true; resolve(input ? null : false); } });
    if (inp) {
      setTimeout(() => { inp.focus(); inp.select(); }, 50);
      inp.addEventListener("keydown", e => { if (e.key === "Enter") finish(inp.value.trim() || null); });
    }
  });
}

function menu(title, entries) {
  return sheet(title, close => el("div.menu", null, entries.filter(Boolean).map(([label, fn, danger]) =>
    el("button" + (danger ? ".danger" : ""), { text: label, onclick: () => { close(); fn(); } }))));
}

// ====================================================================== ağaç seçici
/** Bir yer/kategori seçtirir. Sonuç: uid, "" (belirtilmemiş), null (tümü) ya da undefined (vazgeçildi). */
function pickNode(table, current, { all = false, none = true, counts = false, add = true, exclude = null, title } = {}) {
  return new Promise(resolve => {
    let picked;
    const close = sheet(title || (table === "locations" ? t("Bulunduğu yer:") : t("Kategori:")), closeSheet => {
      const box = el("div.tree");
      const cnt = counts ? Store.itemCounts(table) : null;
      const total = counts ? Store.liveItems().length : 0;
      const choose = v => { picked = v; closeSheet(); };
      const row = (label, value, depth, n) => el("div.node" + (value === current ? ".on" : ""),
        { style: { paddingInlineStart: (8 + depth * 22) + "px" }, onclick: () => choose(value) },
        [el("span.n", { text: label }), n ? el("span.c", { text: fmtNum(n) }) : null]);
      if (all) box.append(row(t("Tümü"), null, 0, total));
      if (none) box.append(row(t("— Belirtilmemiş —"), "", 0, cnt ? cnt.get("") : 0));
      const skip = exclude ? Store.descendants(table, exclude) : new Set();
      for (const n of Store.treeOrdered(table)) {
        if (skip.has(n.uid)) continue;
        let c = 0;
        if (cnt) for (const d of Store.descendants(table, n.uid)) c += cnt.get(d) || 0;
        box.append(row(n.name, n.uid, n.depth, c));
      }
      const wrap = el("div", null, box);
      if (add) {
        wrap.append(el("button.btn.block", { text: table === "locations" ? t("＋ Yeni yer") : t("＋ Yeni kategori"),
          onclick: async () => {
            const uid = await newNodeDialog(table, typeof current === "string" ? current : "");
            if (uid) choose(uid);
          } }));
      }
      return wrap;
    });
    Layers.stack[Layers.stack.length - 1].onClose = () => resolve(picked);
    void close;
  });
}

/** Yeni yer/kategori: ad + üst öğe */
function newNodeDialog(table, parent) {
  return new Promise(resolve => {
    let result = null;
    let par = parent || "";
    const paths = Store.treePaths(table);
    sheet(table === "locations" ? t("Yeni yer") : t("Yeni kategori"), close => {
      const name = el("input.in", { placeholder: table === "locations" ? t("Örn. Balkon dolabı") : t("Örn. Vidalar") });
      const parBtn = el("button.btn.block", { style: { textAlign: "start" } });
      const showPar = () => { parBtn.textContent = par ? paths.get(par) : t("— En üst seviye —"); };
      showPar();
      parBtn.onclick = async () => {
        const v = await pickNode(table, par, { add: false, none: true, title: table === "locations" ? t("Üst yer:") : t("Üst kategori:") });
        if (v !== undefined) { par = v || ""; showPar(); }
      };
      const err = el("div.err");
      setTimeout(() => name.focus(), 80);
      return el("div", null, [
        el("label.f", { text: t("Ad:") }), name,
        el("label.f", { text: table === "locations" ? t("Üst yer:") : t("Üst kategori:") }), parBtn, err,
        el("button.btn.primary.block", { text: t("Ekle"), onclick: async () => {
          if (!name.value.trim()) { err.textContent = t("Lütfen bir ad yazın"); return; }
          result = await Store.addNode(table, name.value, par);
          Cloud.soon();
          close();
        } }),
      ]);
    });
    Layers.stack[Layers.stack.length - 1].onClose = () => resolve(result);
  });
}

// ====================================================================== fotoğraf alma
const PhotoInput = {
  cb: null,
  init() {
    for (const id of ["camInput", "galInput"]) {
      $("#" + id).addEventListener("change", e => {
        const files = [...e.target.files];
        e.target.value = "";
        if (this.cb && files.length) this.cb(files);
      });
    }
  },
  take(cb) { this.cb = cb; $("#camInput").click(); },
  pick(cb) { this.cb = cb; $("#galInput").click(); },
};

// ====================================================================== eşyalar
const SORTS = [["En yeni eklenen", "created_desc"], ["En eski eklenen", "created_asc"], ["Ada göre (A → Z)", "name_asc"],
  ["Ada göre (Z → A)", "name_desc"], ["Kategoriye göre (A → Z)", "category_asc"], ["Kategoriye göre (Z → A)", "category_desc"],
  ["Yere göre (A → Z)", "location_asc"], ["Yere göre (Z → A)", "location_desc"],
  ["Adet (çok → az)", "qty_desc"], ["Adet (az → çok)", "qty_asc"], ["Fiyat (yüksek → düşük)", "price_desc"], ["Fiyat (düşük → yüksek)", "price_asc"],
  ["Dükkan/Kişiye göre (A → Z)", "shop_asc"], ["Dükkan/Kişiye göre (Z → A)", "shop_desc"],
  ["Konuma göre (A → Z)", "place_asc"], ["Konuma göre (Z → A)", "place_desc"]];

const CSORTS = [["İsme göre (A → Z)", "name_asc"], ["İsme göre (Z → A)", "name_desc"], ["Türe göre", "kind_asc"],
  ["Mesleğe göre (A → Z)", "prof_asc"], ["Mesleğe göre (Z → A)", "prof_desc"], ["Yere göre (A → Z)", "place_asc"],
  ["Yere göre (Z → A)", "place_desc"], ["Telefona göre", "phone_asc"]];

// ====================================================================== satın alındığı yer (1.4.0)
const SHOP_CHANNELS = [["shop_whatsapp", "whatsapp", "WhatsApp"], ["shop_telegram", "telegram", "Telegram"]];

/** Dükkan numarasının çalıştığı uygulamaların simgeleri; dokununca o uygulamada sohbet açılır. */
function shopLinks(d, big) {
  const phone = String(d.shop_phone || "").trim();
  const on = SHOP_CHANNELS.filter(([f]) => d[f] && phone);
  if (!on.length) return null;
  return el("span.shoplinks" + (big ? ".big" : ""), null, on.map(([, key, label]) =>
    el("a", { href: "#", title: t("{app} ile yaz: {p}", { app: label, p: phone }),
      onclick: e => { e.preventDefault(); e.stopPropagation(); const u = channelUrl(key, phone); if (u) { toast(t("{app} açılıyor…", { app: label })); openUrl(u); } } },
      [el("img", { src: `img/${key}.png`, alt: label }), big ? label : null])));
}

/** Koyu başlık şeridi: başlığa dokun → sırala, yeniden dokun → ters yön (▲ artan, ▼ azalan).
 *  cols: [[etiket, alan, ilk dokunuşta azalan mı]] */
function sortBar(cols, cur, onPick) {
  const i = cur.lastIndexOf("_"), f = cur.slice(0, i), dir = cur.slice(i + 1);
  return el("div.sortbar", null, cols.map(([label, field, firstDesc]) => {
    const on = f === field;
    return el("button" + (on ? ".on" : ""), { text: t(label) + (on ? (dir === "desc" ? " ▼" : " ▲") : ""),
      onclick: () => onPick(field + "_" + (on ? (dir === "desc" ? "asc" : "desc") : (firstDesc ? "desc" : "asc"))) });
  }));
}

const ItemsPage = {
  search: "", cat: null, loc: null, sort: null, sel: new Set(), scroll: 0, onlyAuto: false, onlyLoan: false,

  render(root) {
    const paths = { categories: Store.treePaths("categories"), locations: Store.treePaths("locations") };
    if (this.cat && !paths.categories.has(this.cat)) this.cat = null;
    if (this.loc && !paths.locations.has(this.loc)) this.loc = null;
    root.append(el("div.pagetitle", { text: t("Eşyalarım") }));

    const input = el("input", { type: "search", value: this.search, placeholder: t("🔍  Eşya adı, kategori, yer ya da not ile ara…") });
    let timer;
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { this.search = input.value; this.renderList(); }, 200); });
    root.append(el("div.search", null, [input, this.search ? el("button.clear", { text: "✕", onclick: () => { this.search = ""; App.render(); } }) : null,
      Undo.stack.length ? el("button.sbtn", { text: "↶", title: t("↶  Geri al") + ": " + Undo.stack[Undo.stack.length - 1].label, onclick: () => Undo.undo() }) : null,
      Voice.available() ? el("button.sbtn.mic", { text: "🎤", title: t("🎤  Sesle ara / ekle"), onclick: () => Voice.start() }) : null]));

    const label = (table, v) => v === null ? (table === "categories" ? t("🗂  Tüm kategoriler") : t("🏠  Tüm yerler"))
      : v === "" ? t("Belirtilmemiş") : paths[table].get(v);
    if (!this.sort) this.sort = SORT_ALIASES[Store.get("sort_items", "")] || Store.get("sort_items", "created_desc");
    if (!SORTS.some(s => s[1] === this.sort)) this.sort = "created_desc";
    const setSort = k => { this.sort = k; Store.set("sort_items", k); App.render(); };
    const sortLabel = t(SORTS.find(s => s[1] === this.sort)[0]);
    root.append(el("div.chips", null, [
      el("button.chip" + (this.cat !== null ? ".on" : ""), { text: label("categories", this.cat), onclick: () => this.pickFilter("categories") }),
      el("button.chip" + (this.loc !== null ? ".on" : ""), { text: label("locations", this.loc), onclick: () => this.pickFilter("locations") }),
      el("button.chip", { text: "⇅  " + sortLabel, onclick: () => menu(t("Sırala:"), SORTS.map(([l, k]) => [(k === this.sort ? "✓  " : "") + t(l), () => setSort(k)])) }),
      el("button.chip", { text: t("🖨  Döküm"), onclick: () => reportPage(this.cat !== null || this.loc === null ? "categories" : "locations",
        this.cat !== null || this.loc === null ? this.cat : this.loc) }),
      el("button.chip" + (this.onlyAuto ? ".on" : ""), { text: t("⚡ Kontrol edilmemiş fiyatlar ({n})",
        { n: fmtNum(Store.liveItems().filter(isAutoPrice).length) }), onclick: () => { this.onlyAuto = !this.onlyAuto; if (this.onlyAuto) this.onlyLoan = false; App.render(); } }),
      el("button.chip", { text: t("🛒 Alışveriş listesi ({n})", { n: fmtNum(Store.shoppingList().length) }), onclick: () => shoppingPage() }),
      (() => { const loans = Store.liveItems().filter(d => d.loan_to), late = loans.filter(d => overdueDays(d) > 0).length;
        return el("button.chip" + (this.onlyLoan ? ".on" : "") + (late ? ".late" : ""), { text: t("🤝 Ödünçtekiler ({n})", { n: loans.length }) + (late ? t(" · ⚠ {n} gecikti", { n: late }) : ""),
          onclick: () => { this.onlyLoan = !this.onlyLoan; if (this.onlyLoan) this.onlyAuto = false; App.render(); } }); })(),
      el("button.chip", { text: t("🗑 Çöp kutusu ({n})", { n: fmtNum(Store.trashItemsList().length) }), onclick: () => trashPage() }),
      this.cat !== null || this.loc !== null ? el("button.chip.x", { text: "✕  " + t("Filtreleri temizle"), onclick: () => { this.cat = this.loc = null; App.render(); } }) : null,
    ]));
    this.summary = el("div.summary");
    this.list = el("div");
    root.append(this.summary, this.list);
    root.append(el("button.fab", { onclick: () => itemForm() }, [el("b", { text: "＋" }), t("Yeni Eşya")]));
    this.renderList();
  },

  async pickFilter(table) {
    const cur = table === "categories" ? this.cat : this.loc;
    const v = await pickNode(table, cur, { all: true, none: true, counts: true, add: false,
      title: table === "categories" ? t("Kategoriler") : t("Yerler") });
    if (v === undefined) return;
    if (table === "categories") this.cat = v; else this.loc = v;
    App.render();
  },

  filterSet(table, v) {
    if (v === null) return null;
    if (v === "") return new Set([""]);
    return Store.descendants(table, v);
  },

  items() {
    const all = Store.listItems({ search: this.search, sort: this.sort,
      categories: this.filterSet("categories", this.cat), locations: this.filterSet("locations", this.loc) });
    return this.onlyAuto ? all.filter(isAutoPrice) : this.onlyLoan ? all.filter(d => d.loan_to) : all;
  },

  renderList() {
    const items = this.items();
    this.list.innerHTML = "";
    const qty = items.reduce((s, d) => s + d.quantity, 0);
    let sum = t("{n} eşya listeleniyor · toplam {q} adet", { n: fmtNum(items.length), q: fmtNum(qty) });
    const totals = Store.totals(items);
    const parts = CURRENCIES.filter(([c]) => c in totals).map(([c]) => fmtPrice(totals[c], c));
    if (parts.length) sum += t(" · Değer: ") + parts.join(" + ");
    const nAuto = items.filter(isAutoPrice).length;
    if (nAuto) sum += t(" · ⚡ {n} fiyat otomatik (kontrol edilmedi) · ✎ sizin girdiğiniz", { n: fmtNum(nAuto) });
    this.summary.textContent = sum;
    const ans = answerCard(this.search, items);
    if (ans) this.list.append(ans);
    if (!items.length) {
      const none = !Store.liveItems().length;
      if (this.onlyAuto && !none) { this.list.append(el("div.empty", { text: t("Kontrol edilmemiş otomatik fiyat kalmadı. ✓") })); return; }
      if (this.onlyLoan && !none) { this.list.append(el("div.empty", { text: t("Ödünç verilmiş eşya yok.") })); return; }
      this.list.append(el("div.empty", { text: none ? t("Henüz eşya eklenmemiş.\n\n„＋ Yeni Eşya“ düğmesiyle ilk eşyanızı ekleyin.")
        : t("Aramanıza uyan eşya bulunamadı.") }));
    }
    const frag = document.createDocumentFragment();
    for (const d of items) frag.append(this.card(d));
    this.list.append(frag);
    this.renderSelBar();
  },

  card(d) {
    const thumb = el("div.thumb", { text: "📦" });
    const pics = d.photos.filter(p => !isReceipt(p));
    if (pics.length) PhotoCache.url(pics[0], true).then(u => { if (u) { thumb.textContent = ""; thumb.style.backgroundImage = `url("${u}")`; } });
    const qtyBox = el("div.qty", null, [
      el("button", { text: "+", "aria-label": t("Adedi artır"), onclick: e => { e.stopPropagation(); this.qty(d.uid, 1); } }),
      el("span", { text: fmtNum(d.quantity) }),
      el("button", { text: "−", "aria-label": t("Adedi azalt"), onclick: e => { e.stopPropagation(); this.qty(d.uid, -1); } }),
      d.quantity === 0 ? el("span.zero", { text: t("Kalmadı") }) : isLow(d) ? el("span.zero.low", { text: t("⚠ Az kaldı") }) : null,
    ]);
    const meta = el("div.meta");
    if (d.category_path) meta.append(el("span.tag", { text: d.category_path }));
    if (d.location_path) meta.append(el("span.tag.loc", { text: "📍 " + d.location_path }));
    if (!d.category_path && !d.location_path) meta.append(t("Belirtilmemiş"));
    if (d.loan_to) meta.append(el("span.tag.loan" + (overdueDays(d) > 0 ? ".late" : ""), { text: loanText(d) }));
    const card = el("div.card.item" + (this.sel.has(d.uid) ? ".sel" : ""), { "data-uid": d.uid }, [
      thumb,
      el("div.body", null, [
        el("div.name", { text: d.name }), meta,
        el("div.price", null, [
          d.price != null ? el("span" + (isAutoPrice(d) ? ".autoprice" : ".myprice"), { text: priceMark(d) + fmtPrice(d.price, d.currency),
            title: isAutoPrice(d) ? t("⚡ Otomatik (tahmini) fiyat — henüz kontrol edilmedi") : t("✎ Sizin girdiğiniz fiyat") }) : null,
          pics.length > 1 ? el("span", { text: (d.price != null ? "  ·  " : "") + t("{n} fotoğraf", { n: pics.length }) }) : null,
          pics.length < d.photos.length ? el("span", { text: "  ·  🧾 " + (d.photos.length - pics.length) }) : null]),
        shopTitle(d) ? el("div.shopline", null, [el("span", { text: "🏪 " + (String(d.shop_name || "").trim() || String(d.shop_phone || "").trim() || "—") }),
          String(d.shop_place || "").trim() ? el("span.shopplace", { text: "📍 " + String(d.shop_place).trim() }) : null, shopLinks(d, false)]) : null,
      ]),
      qtyBox,
    ]);
    let pressTimer, longPressed = false;
    card.addEventListener("touchstart", () => { longPressed = false; pressTimer = setTimeout(() => { longPressed = true; this.toggleSel(d.uid); if (navigator.vibrate) navigator.vibrate(20); }, 520); }, { passive: true });
    for (const ev of ["touchend", "touchmove", "touchcancel"]) card.addEventListener(ev, () => clearTimeout(pressTimer), { passive: true });
    card.addEventListener("contextmenu", e => { e.preventDefault(); if (!longPressed) this.toggleSel(d.uid); longPressed = true; });
    card.addEventListener("click", () => {
      if (longPressed) { longPressed = false; return; }
      if (this.sel.size) this.toggleSel(d.uid); else itemDetail(d.uid);
    });
    return card;
  },

  async qty(uid, delta) {
    Undo.remember(t("Adet değişti"), [uid], "qty:" + uid);
    await Store.changeQuantity(uid, delta);
    Cloud.soon();
    const keep = window.scrollY;
    this.renderList();
    window.scrollTo(0, keep);
  },

  toggleSel(uid) {
    if (this.sel.has(uid)) this.sel.delete(uid); else this.sel.add(uid);
    const c = this.list.querySelector(`[data-uid="${uid}"]`);
    if (c) c.classList.toggle("sel", this.sel.has(uid));
    this.renderSelBar();
  },

  renderSelBar() {
    const old = $(".selbar");
    if (old) old.remove();
    if (!this.sel.size || App.tab !== 0) return;
    const ids = () => [...this.sel].filter(u => Store.t.items.has(u));
    document.body.append(el("div.selbar", null, [
      el("span", { text: t("{n} seçili", { n: this.sel.size }) }),
      el("button", { text: t("Tümünü seç"), onclick: () => { for (const d of this.items()) this.sel.add(d.uid); this.renderList(); } }),
      el("button", { text: t("Kategori"), onclick: () => moveItems(ids(), "categories") }),
      el("button", { text: t("Yer"), onclick: () => moveItems(ids(), "locations") }),
      el("button", { text: t("✎ Onayla"), title: t("✎  Fiyatı onayla (benim fiyatım)"),
        onclick: async () => { await setAutoPrice(ids(), false); this.clearSel(); } }),
      el("button.danger", { text: t("Sil"), onclick: () => deleteItems(ids()) }),
      el("button", { text: "✕", onclick: () => this.clearSel() }),
    ]));
  },

  clearSel() { this.sel.clear(); this.renderList(); },
};

async function moveItems(uids, table) {
  if (!uids.length) return;
  const v = await pickNode(table, undefined, { none: true, add: true, title: table === "categories" ? t("Kategoriye taşı") : t("Yere taşı") });
  if (v === undefined) return;
  Undo.remember(t("{n} eşya taşındı", { n: uids.length }), uids);
  await Store.updateItems(uids, table === "categories" ? "category" : "location", v || "");
  Cloud.soon();
  ItemsPage.sel.clear();
  toast(t("{n} eşya taşındı", { n: uids.length }));
  App.render();
}

/** Silinen eşya çöp kutusuna gider (30 gün); "↶ Geri al" ile hemen geri alınabilir. */
async function deleteItems(uids) {
  if (!uids.length) return false;
  const msg = (uids.length === 1 ? t("„{name}“ çöp kutusuna taşınsın mı?", { name: Store.t.items.get(uids[0]).name })
    : t("Seçili {n} eşya çöp kutusuna taşınsın mı?", { n: uids.length }))
    + "\n\n" + t("{n} gün içinde çöp kutusundan geri yükleyebilir ya da „↶ Geri al“ diyebilirsiniz.", { n: TRASH_DAYS });
  if (!(await ask(msg, { yes: t("Sil"), danger: true }))) return false;
  Undo.remember(t("{n} eşya silindi", { n: uids.length }), uids);
  await Store.trashItems(uids);
  Cloud.soon();
  for (const u of uids) ItemsPage.sel.delete(u);
  App.render();
  Undo.offer(t("{n} eşya çöp kutusuna taşındı", { n: uids.length }));
  return true;
}

function itemDetail(uid) {
  const close = fullPage({ title: Store.t.items.get(uid).name, build: (closeIt, bar) => {
    const box = el("div");
    const draw = () => {
      const d = Store.t.items.get(uid);
      if (!d || d.deleted || d.trashed_at) { closeIt(); return; }
      const pics = d.photos.filter(p => !isReceipt(p)), recs = d.photos.filter(isReceipt);
      bar.querySelector("h2").textContent = d.name;
      box.innerHTML = "";
      const paths = { c: Store.treePaths("categories"), l: Store.treePaths("locations") };
      if (pics.length) {
        const g = el("div.gallery");
        pics.forEach((p, i) => {
          const img = el("img" + (pics.length === 1 ? ".only" : ""), { alt: "", onclick: () => viewer(pics, i) });
          PhotoCache.url(p).then(u => { if (u) img.src = u; else img.alt = t("Fotoğraf bulunamadı"); });
          g.append(img);
        });
        box.append(g);
      } else {
        box.append(el("div.nophoto", { text: t("Fotoğraf yok\n(Düzenle ile ekleyebilirsiniz)") }));
      }
      const stepper = el("div.stepper", null, [
        el("button", { text: "−", onclick: async () => { await Store.changeQuantity(uid, -1); Cloud.soon(); draw(); } }),
        el("input", { value: fmtNum(d.quantity), readOnly: true }),
        el("button", { text: "+", onclick: async () => { await Store.changeQuantity(uid, 1); Cloud.soon(); draw(); } }),
      ]);
      const fact = (k, v) => el("div", null, [el("span", { text: k }), el("span", { text: v })]);
      box.append(el("div.facts", null, [
        el("div", null, [el("span", { text: t("Adet:") }), el("span", null, [stepper,
          d.min_qty ? el("div.hint" + (isLow(d) ? ".lowtxt" : ""), { text: (isLow(d) ? t("⚠ Az kaldı") + " · " : "") + t("En az: {n}", { n: d.min_qty }) }) : null])]),
        fact(t("Kategori:"), paths.c.get(d.category) || t("Belirtilmedi")),
        fact(t("Bulunduğu yer:"), paths.l.get(d.location) || t("Belirtilmedi")),
        fact(t("Alış fiyatı:"), d.price == null ? fmtPrice(d.price, d.currency)
          : priceMark(d) + fmtPrice(d.price, d.currency) + (isAutoPrice(d) ? "  ·  " + t("⚡ otomatik — kontrol edilmedi") : "")),
        fact(t("Ekleme tarihi:"), fmtDate(d.created_at)),
        shopTitle(d) ? el("div", null, [el("span", { text: t("Satın alındığı yer:") }), el("span", null, [
          [d.shop_name, d.shop_place, d.shop_phone ? "☎ " + d.shop_phone : ""].filter(Boolean).join("\n"),
          shopLinks(d, true)])]) : null,
        d.notes ? fact(t("Notlar:"), d.notes) : null,
        d.loan_to ? el("div", null, [el("span", { text: t("Ödünç:") }), el("span" + (overdueDays(d) > 0 ? ".latetxt" : ""), { text: loanText(d) + (d.loan_phone ? "\n☎ " + d.loan_phone : "") })]) : null,
        (d.loan_history || []).length ? fact(t("Geçmiş:"), d.loan_history.slice(-5).reverse().map(h => `${h.to}: ${fmtDay(h.date)} → ${fmtDay(h.returned)}`).join("\n")) : null,
      ]));
      if (recs.length) {
        box.append(el("div.formsec", { text: t("🧾  Fatura / fiş ({n})", { n: recs.length }) }));
        const g = el("div.gallery");
        recs.forEach((p, i) => {
          const img = el("img", { alt: "", onclick: () => viewer(recs, i) });
          PhotoCache.url(p, true).then(u => { if (u) img.src = u; });
          g.append(img);
        });
        box.append(g);
      }
      box.append(el("div.hrow", { style: { marginTop: "16px" } }, [
        el("button.btn.primary.grow", { text: t("✎  Düzenle"), onclick: () => itemForm(uid, draw) }),
        el("button.btn.danger", { text: t("Sil"), onclick: async () => { if (await deleteItems([uid])) closeIt(); } }),
      ]));
      box.append(el("div.hrow", { style: { marginTop: "8px" } }, [
        d.loan_to ? el("button.btn.primary.grow", { text: t("↩  Geri geldi"), onclick: () => giveBack(uid, draw) })
          : el("button.btn.grow", { text: t("🤝  Ödünç ver"), onclick: () => lendForm(uid, draw) }),
        el("button.btn.grow" + (d.to_buy || isLow(d) ? ".primary" : ""), { text: d.to_buy || isLow(d) ? t("🛒  Listede") : t("🛒  Listeye ekle"),
          disabled: isLow(d), onclick: async () => { Undo.remember(t("Alışveriş listesi değişti"), [uid]); await Store.patchItems([uid], { to_buy: !d.to_buy }); Cloud.soon(); draw(); } }),
      ]));
      box.append(el("div.hrow", { style: { marginTop: "8px" } }, [
        el("button.btn.grow", { text: t("Kategoriye taşı"), onclick: async () => { await moveItems([uid], "categories"); draw(); } }),
        el("button.btn.grow", { text: t("Yere taşı"), onclick: async () => { await moveItems([uid], "locations"); draw(); } }),
      ]));
      if (d.price != null) box.append(el("div.hrow", { style: { marginTop: "8px" } }, [
        isAutoPrice(d)
          ? el("button.btn.primary.grow", { text: t("✎  Fiyatı onayla (benim fiyatım)"), onclick: async () => { await setAutoPrice([uid], false); draw(); } })
          : el("button.btn.grow", { text: t("⚡  Otomatik fiyat olarak işaretle"), onclick: async () => { await setAutoPrice([uid], true); draw(); } }),
      ]));
    };
    draw();
    return box;
  }, onClose: () => App.render() });
  return close;
}

/** Döküm: bir kategorideki ya da yerdeki bütün eşyalar tek sayfada; yazdırılabilir / PDF kaydedilebilir. */
function reportPage(table, node) {
  const st = { table, node: node === undefined ? null : node, photos: true };
  fullPage({ title: t("Döküm"), build: () => {
    const box = el("div");
    const draw = () => {
      box.innerHTML = "";
      const paths = Store.treePaths(st.table);
      const isCat = st.table === "categories";
      const scope = st.node === null ? (isCat ? t("Bütün kategoriler") : t("Bütün yerler"))
        : st.node === "" ? t("Belirtilmemiş") : paths.get(st.node);
      const set = st.node === null ? null : st.node === "" ? new Set([""]) : Store.descendants(st.table, st.node);
      const items = Store.listItems({ sort: "name_asc", [isCat ? "categories" : "locations"]: set });
      const key = isCat ? "category" : "location";
      const otherPath = isCat ? "location_path" : "category_path";
      const order = new Map(Store.treeOrdered(st.table).map((n, i) => [n.uid, i]));
      const groups = new Map();
      for (const d of items) { if (!groups.has(d[key])) groups.set(d[key], []); groups.get(d[key]).push(d); }
      const gids = [...groups.keys()].sort((a, b) => (a === "") - (b === "") || (order.get(a) || 0) - (order.get(b) || 0));
      const controls = el("div.noprint", null, [
        el("div.seg", null, [["categories", t("Kategoriye göre")], ["locations", t("Yere göre")]].map(([k, l]) =>
          el("button" + (st.table === k ? ".on" : ""), { text: l, onclick: () => { st.table = k; st.node = null; draw(); } }))),
        el("div.hrow", { style: { marginTop: "8px" } }, [
          el("button.btn.grow", { text: "▾  " + scope, style: { textAlign: "start" }, onclick: async () => {
            const v = await pickNode(st.table, st.node, { all: true, none: true, counts: true, add: false,
              title: isCat ? t("Kategoriler") : t("Yerler") });
            if (v !== undefined) { st.node = v; draw(); }
          } }),
          el("button.btn" + (st.photos ? ".primary" : ""), { text: "📷", title: t("Fotoğraflarla"), onclick: () => { st.photos = !st.photos; draw(); } }),
        ]),
        el("button.btn.primary.block", { text: t("🖨  Yazdır / PDF olarak kaydet"), onclick: () => printReport(t("Döküm: {scope}", { scope })) }),
      ]);
      const qty = items.reduce((a, d) => a + d.quantity, 0);
      const totals = Store.totals(items);
      const value = CURRENCIES.filter(([c]) => c in totals).map(([c]) => fmtPrice(totals[c], c)).join(" + ");
      const rep = el("div.report", null, [
        el("h1", { text: t("Döküm: {scope}", { scope }) }),
        el("div.rsum", { text: ["Organizer", fmtDate(nowStr()), t("{n} eşya · toplam {q} adet", { n: fmtNum(items.length), q: fmtNum(qty) }),
          value ? t("Değer:") + " " + value : ""].filter(Boolean).join(" · ") }),
        !items.length ? el("div.empty", { text: t("Bu bölümde kayıtlı eşya yok.") }) : null,
      ]);
      for (const g of gids) {
        const rows = groups.get(g);
        rep.append(el("h2", null, [g ? paths.get(g) : t("Belirtilmemiş"),
          el("small", { text: " · " + t("{n} eşya · toplam {q} adet", { n: fmtNum(rows.length), q: fmtNum(rows.reduce((a, d) => a + d.quantity, 0)) }) })]));
        for (const d of rows) {
          const th = st.photos ? el("div.rthumb") : null;
          if (th && d.photos.length) PhotoCache.url(d.photos[0], true).then(u => { if (u) th.style.backgroundImage = `url("${u}")`; });
          rep.append(el("div.rrow", null, [th,
            el("div.rbody", null, [
              el("div.rname", { text: d.name }),
              el("div.rmeta", { text: [d[otherPath] ? (isCat ? "📍 " : "🗂 ") + d[otherPath] : "", d.price != null ? fmtPrice(d.price, d.currency) : "", d.notes].filter(Boolean).join(" · ") }),
            ]),
            el("div.rqty", { text: fmtNum(d.quantity) }),
          ]));
        }
      }
      box.append(controls, rep);
    };
    draw();
    return box;
  } });
  Layers.stack[Layers.stack.length - 1].layer.classList.add("report-layer");
}

function printReport(title) {
  if (Native && Native.printPage) Native.printPage(title);
  else window.print();
}

function viewer(photos, start) {
  let i = start;
  const img = el("img");
  const count = el("span");
  const show = () => { count.textContent = `${i + 1} / ${photos.length}`; PhotoCache.url(photos[i]).then(u => { img.src = u || ""; }); };
  const go = d => { i = (i + d + photos.length) % photos.length; show(); };
  const node = el("div.viewer", null, [img, el("button", { text: "✕", onclick: () => close() }),
    photos.length > 1 ? el("div.nav", null, [el("button", { text: I18N.rtl ? "▶" : "◀", onclick: () => go(-1) }), count,
      el("button", { text: I18N.rtl ? "◀" : "▶", onclick: () => go(1) })]) : null]);
  node.addEventListener("click", e => { if (e.target === node) close(); });
  const close = Layers.push(node);
  show();
}

/** Fotoğraf seçici (eşya ve usta/dükkan formlarında). İlk fotoğraf favoridir; listelerde o görünür. */
function photoEditor(names, receipts) {
  const photos = (names || []).map(n => ({ name: n }));
  const box = el("div.photos");
  const draw = () => {
    box.innerHTML = "";
    photos.forEach((p, i) => {
      const ph = el("div.ph" + (i === 0 && photos.length > 1 ? ".first" : ""), null, el("button", { text: "✕", "aria-label": t("Seçileni kaldır"),
        onclick: e => { e.stopPropagation(); photos.splice(i, 1); draw(); } }));
      if (p.url) ph.style.backgroundImage = `url("${p.url}")`;
      else PhotoCache.url(p.name, true).then(u => { if (u) ph.style.backgroundImage = `url("${u}")`; });
      ph.addEventListener("click", () => menu(t("Fotoğraf"), [
        i > 0 && !receipts ? [t("⭐ Favori yap"), () => { photos.unshift(...photos.splice(i, 1)); draw(); }] : null,
        p.name ? [t("🔍  Büyüt"), () => viewer(photos.filter(x => x.name).map(x => x.name), photos.filter(x => x.name).indexOf(p))] : null,
        [t("Seçileni kaldır"), () => { photos.splice(i, 1); draw(); }, true],
      ]));
      box.append(ph);
    });
    if (!photos.length) box.append(el("div.hint", { text: t("Fotoğraf yok") }));
  };
  const addFiles = files => {
    for (const f of files) photos.push({ blob: f, url: URL.createObjectURL(f) });
    draw();
  };
  draw();
  return {
    node: el("div", null, [
      el("label.f", { text: receipts ? t("🧾  Fatura / fiş") : t("Fotoğraflar") }), box,
      el("div.photoadd", null, [
        el("button.btn.primary", { text: t("📷  Fotoğraf çek"), onclick: () => PhotoInput.take(addFiles) }),
        el("button.btn", { text: t("🖼  Galeriden seç"), onclick: () => PhotoInput.pick(addFiles) }),
      ]),
      el("div.hint", { text: receipts ? t("Faturanın, fişin ya da garanti belgesinin fotoğrafını ekleyin (sürükleyip bırakabilirsiniz).").replace(/\s*\([^)]*\)/, "")
        : t("⭐ işaretli ilk fotoğraf favoridir ve listede o görünür. Bir fotoğrafa dokunarak favori yapabilirsiniz.") }),
    ]),
    /** Yeni fotoğrafları küçültüp kaydeder, dosya adlarını sırasıyla döndürür */
    async commit() {
      const out = [];
      for (const p of photos) {
        if (p.name) { out.push(p.name); continue; }
        const big = await shrinkPhoto(p.blob);
        if (!big) continue;
        const small = await shrinkPhoto(big, 320, 60000).catch(() => null);
        p.name = await Store.addPhoto(big, small, receipts ? RECEIPT_PREFIX : "");
        URL.revokeObjectURL(p.url);
        out.push(p.name);
      }
      return out;
    },
  };
}

function localInputValue(created) {
  const m = /^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d)/.exec(created || "");
  return m ? `${m[1]}T${m[2]}` : nowStr().slice(0, 16).replace(" ", "T");
}

/** Eşya ekle / düzenle */
function itemForm(uid, after, defaults) {
  const d = uid ? Store.t.items.get(uid) : null;
  defaults = defaults || {};
  const st = {
    category: d ? d.category : (ItemsPage.cat || ""), location: d ? d.location : (defaults.location || ItemsPage.loc || ""),
    busy: false,
  };
  const pe = photoEditor(d ? d.photos.filter(p => !isReceipt(p)) : []);
  const re = photoEditor(d ? d.photos.filter(isReceipt) : [], true);
  const paths = () => ({ categories: Store.treePaths("categories"), locations: Store.treePaths("locations") });
  const name = el("input.in", { value: d ? d.name : (defaults.name || ""), placeholder: t("Örn. 4x40 sunta vidası") });
  const qty = el("input", { type: "number", inputmode: "numeric", min: 0, value: d ? d.quantity : (defaults.quantity || 1) });
  const minQty = el("input.in", { type: "number", inputmode: "numeric", min: 0, value: d && d.min_qty ? d.min_qty : "", placeholder: t("Uyarı yok"), style: { width: "130px" } });
  const step = delta => { qty.value = Math.max(0, (parseInt(qty.value, 10) || 0) + delta); };
  const price = el("input.in.grow", { type: "number", inputmode: "decimal", step: "0.01", min: 0, value: d && d.price != null ? d.price : "", placeholder: "0.00" });
  const cur = el("select.in", { style: { width: "auto" } }, CURRENCIES.map(([c, sym, n]) => el("option", { value: c, text: `${sym}  ${t(n)}` })));
  cur.value = d ? d.currency : Store.get("default_currency", "TRY");
  // otomatik (tahmini) fiyat: fiyat ya da para birimi değişince ya da işaret kaldırılınca kullanıcının fiyatı olur
  const autoChk = el("input", { type: "checkbox" });
  autoChk.checked = !!(d && isAutoPrice(d));
  const autoRow = d && isAutoPrice(d) ? el("label.autorow", null, [autoChk, el("span", { text: t("⚡ Otomatik fiyat — henüz kontrol edilmedi") })]) : null;
  price.addEventListener("input", () => { autoChk.checked = false; });
  cur.addEventListener("change", () => { autoChk.checked = false; });
  const date = el("input.in", { type: "datetime-local", value: localInputValue(d && d.created_at) });
  const notes = el("textarea.in", { placeholder: t("Ölçü, marka, nereden alındığı gibi notlar…") });
  notes.value = d ? d.notes : "";
  // ---- satın alındığı yer
  const shops = Store.knownShops();
  const shopName = el("input.in", { value: d ? d.shop_name || "" : "", placeholder: t("Örn. Yıldız Hırdavat"), list: "shopList" });
  const shopList = el("datalist", { id: "shopList" }, [...shops.keys()].map(n => el("option", { value: n })));
  const shopPlace = el("input.in", { value: d ? d.shop_place || "" : "", placeholder: t("Semt, çarşı, sokak ya da adres") });
  const shopPhone = el("input.in.ltr.grow", { type: "tel", value: d ? d.shop_phone || "" : "", placeholder: t("Örn. 0532 123 45 67 ya da +963 …") });
  const chan = { shop_whatsapp: !!(d && d.shop_whatsapp), shop_telegram: !!(d && d.shop_telegram) };
  const chanStatus = el("div.chstatus");
  const toggles = SHOP_CHANNELS.map(([field, key, label]) => {
    const b = el("button.chtoggle", { type: "button" }, [el("img", { src: `img/${key}.png`, alt: "" }), el("span")]);
    b.draw = () => {
      b.classList.toggle("on", chan[field]);
      b.lastChild.textContent = (chan[field] ? "✓ " : "") + label;
      b.title = chan[field] ? t("{app} bu numarada çalışıyor. Kapatmak için tıklayın.", { app: label })
        : t("{app} bu numarada çalışıyorsa tıklayıp etkinleştirin.", { app: label });
    };
    b.onclick = () => { chan[field] = !chan[field]; drawChan(); };
    return b;
  });
  const drawChan = () => {
    for (const b of toggles) b.draw();
    const on = SHOP_CHANNELS.filter(([f]) => chan[f]).map(([, , l]) => l);
    chanStatus.classList.toggle("on", on.length > 0);
    chanStatus.textContent = on.length ? "✓ " + t("Bu numarada çalışan: {x}", { x: on.join(" + ") }) + (shopPhone.value.trim() ? "" : "  " + t("(numara yazılmadı)"))
      : t("Bu numara için WhatsApp / Telegram seçilmedi. Çalışanın düğmesine tıklayın.");
  };
  shopPhone.addEventListener("input", drawChan);
  shopName.addEventListener("change", () => {
    const info = shops.get(shopName.value.trim());
    if (!info) return;
    if (!shopPlace.value.trim()) shopPlace.value = info.shop_place;
    if (!shopPhone.value.trim()) { shopPhone.value = info.shop_phone; chan.shop_whatsapp = info.shop_whatsapp; chan.shop_telegram = info.shop_telegram; }
    drawChan();
  });
  drawChan();
  const err = el("div.err");
  const nodeBtn = table => {
    const b = el("button.btn.block", { style: { textAlign: "start", marginTop: 0 } });
    const key = table === "categories" ? "category" : "location";
    const show = () => { b.textContent = paths()[table].get(st[key]) || t("Belirtilmedi"); };
    b.onclick = async () => { const v = await pickNode(table, st[key]); if (v !== undefined) { st[key] = v || ""; show(); } };
    show();
    return b;
  };

  fullPage({ title: d ? t("Eşyayı düzenle") : t("Yeni eşya"), saveLabel: t("Kaydet"),
    onSave: async close => {
      if (st.busy) return;
      if (!name.value.trim()) { err.textContent = t("Lütfen bir ad yazın"); name.focus(); return; }
      st.busy = true;
      err.className = "ok";
      err.textContent = t("Kaydediliyor…");
      try {
        const names = [...await pe.commit(), ...await re.commit()];
        const dv = date.value ? date.value.replace("T", " ") + ":00" : nowStr();
        await Store.saveItem({ name: name.value, quantity: qty.value, category: st.category, location: st.location,
          price: price.value === "" ? null : parseFloat(price.value), currency: cur.value, notes: notes.value, created_at: dv,
          shop_name: shopName.value, shop_place: shopPlace.value, shop_phone: shopPhone.value, ...chan,
          price_auto: !!autoRow && autoChk.checked, min_qty: parseInt(minQty.value, 10) || 0 }, names, uid);
        Cloud.soon();
        close();
        toast(t("Kaydedildi"));
        if (after) after(); else App.render();
      } catch (e) {
        err.className = "err";
        err.textContent = String(e);
        st.busy = false;
      }
    },
    build: () => el("div", null, [
      pe.node,
      el("label.f", { text: t("Adı:") }), name,
      el("label.f", { text: t("Adet:") }),
      el("div.stepper", null, [el("button", { text: "−", onclick: () => step(-1) }), qty, el("button", { text: "+", onclick: () => step(1) })]),
      el("label.f", { text: t("En az adet:") }), minQty,
      el("div.hint", { text: t("Adet bunun altına düşünce eşya alışveriş listesine eklenir (0 = uyarı yok)") }),
      el("label.f", { text: t("Kategori:") }), nodeBtn("categories"),
      el("label.f", { text: t("Bulunduğu yer:") }), nodeBtn("locations"),
      el("label.f", { text: t("Alış fiyatı:") }), el("div.hrow", null, [price, cur]), autoRow,
      el("div.formsec", { text: t("🏪  Satın alındığı yer") }),
      el("label.f", { text: t("Dükkan/Kişi Adı:") }), shopName, shopList,
      el("label.f", { text: t("Dükkan/Kişi Yeri:") }), shopPlace,
      el("label.f", { text: t("İletişim numarası:") }), shopPhone,
      el("div.chtoggles", null, toggles), chanStatus,
      el("label.f", { text: t("Ekleme tarihi:") }), date,
      el("label.f", { text: t("Notlar:") }), notes,
      re.node,
      err,
    ]) });
  if (!d) setTimeout(() => name.focus(), 120);
}

// ====================================================================== ustalar
const CHANNELS = [["has_whatsapp", "whatsapp", "WhatsApp"], ["has_telegram", "telegram", "Telegram"], ["has_call", "call", "Telefonla arama"]];

function channelUrl(key, phone) {
  const digits = phoneForLinks(phone, Store.get("country_code", "90"));
  if (!digits) return "";
  return { whatsapp: `https://wa.me/${digits}`, telegram: `https://t.me/+${digits}`, call: `tel:+${digits}` }[key];
}

const ContactsPage = {
  search: "", kind: null, sort: null,
  render(root) {
    if (!this.sort) this.sort = Store.get("sort_contacts", "name_asc");
    root.append(el("div.pagetitle", { text: t("Ustalar ve Dükkanlar") }));
    const input = el("input", { type: "search", value: this.search, placeholder: t("🔍  İsim, meslek, yer ya da telefon numarası ile ara…") });
    let timer;
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { this.search = input.value; this.renderList(); }, 200); });
    root.append(el("div.search", null, input));
    root.append(el("div.seg", { style: { marginTop: "10px" } }, [[null, t("Hepsi")], ["usta", t("🔧  Ustalar")], ["dukkan", t("🏪  Dükkanlar")]].map(([k, l]) =>
      el("button" + (this.kind === k ? ".on" : ""), { text: l, onclick: () => { this.kind = k; App.render(); } }))));
    if (!CSORTS.some(s => s[1] === this.sort)) this.sort = "name_asc";
    const setSort = k => { this.sort = k; Store.set("sort_contacts", k); App.render(); };
    root.append(el("div.chips", null, [
      el("button.chip", { style: { gridColumn: "1 / -1" }, text: "⇅  " + t(CSORTS.find(s => s[1] === this.sort)[0]),
        onclick: () => menu(t("Sırala:"), CSORTS.map(([l, k]) => [(k === this.sort ? "✓  " : "") + t(l), () => setSort(k)])) }),
    ]));
    this.summary = el("div.summary");
    this.list = el("div");
    root.append(this.summary, this.list);
    root.append(el("button.fab", { onclick: () => contactForm() }, [el("b", { text: "＋" }), t("Yeni Usta / Dükkan")]));
    this.renderList();
  },
  renderList() {
    const rows = Store.listContacts({ search: this.search, kind: this.kind, sort: this.sort });
    const all = Store.listContacts();
    this.summary.textContent = t("{a} usta · {b} dükkan", { a: all.filter(c => c.kind === "usta").length, b: all.filter(c => c.kind !== "usta").length });
    this.list.innerHTML = "";
    if (!rows.length) this.list.append(el("div.empty", { text: all.length ? t("Aramanıza uyan kayıt bulunamadı.")
      : t("Henüz usta ya da dükkan eklenmemiş.\n\n„＋ Yeni Usta / Dükkan“ ile ekleyin.") }));
    for (const c of rows) {
      const ch = el("div.channels");
      for (const [field, key, label] of CHANNELS) {
        const on = c[field] && c.phone;
        ch.append(el("a" + (on ? "" : ".off"), { href: "#", title: on ? t("{label} ile ulaş", { label: t(label) }) : t("{label} yok", { label: t(label) }),
          onclick: e => { e.preventDefault(); const u = channelUrl(key, c.phone); if (u) openUrl(u); } },
          [el("img", { src: `img/${key}.png`, alt: "" }), key === "call" ? t("Ara") : label]));
      }
      this.list.append(el("div.card.contact", null, [
        el("div.row1", null, [
          this.avatar(c),
          el("div", { style: { flex: 1, minWidth: 0 } }, [
            el("div.name", { text: c.name }),
            el("div.meta.prof", null, [Icons.badge(c.profession, c.kind, 22),
              el("span", { text: [c.profession, c.place].filter(Boolean).join(" · ") || (c.kind === "usta" ? t("Usta") : t("Dükkan")) })]),
            c.phone ? el("div.phone", { text: c.phone }) : null,
          ]),
          el("button.more", { text: "⋮", onclick: () => this.actions(c) }),
        ]),
        c.notes ? el("div.hint", { text: c.notes }) : null,
        (c.jobs || []).length ? el("div.hint.jobsum", { text: "🧾 " + jobsSummary(c.jobs) }) : null,
        ch,
      ]));
    }
  },
  avatar(c) {
    const photos = c.photos || [];
    if (!photos.length) return el("div.avatar.icon", null, Icons.badge(c.profession, c.kind, 52));
    const a = el("div.avatar.pic", { onclick: () => viewer(photos, 0) },
      photos.length > 1 ? el("span.count", { text: String(photos.length) }) : null);
    PhotoCache.url(photos[0], true).then(u => { if (u) a.style.backgroundImage = `url("${u}")`; });
    return a;
  },
  actions(c) {
    menu(c.name, [
      [t("✎  Düzenle"), () => contactForm(c.uid)],
      c.phone ? [t("Numarayı kopyala"), async () => { await copyText(c.phone); toast(t("Numara kopyalandı")); }] : null,
      [t("Sil"), async () => {
        if (await ask(t("„{name}“ silinsin mi?", { name: c.name }), { yes: t("Sil"), danger: true })) {
          await Store.deleteContacts([c.uid]); Cloud.soon(); App.render();
        }
      }, true],
    ]);
  },
};

function contactForm(uid) {
  const c = uid ? Store.t.contacts.get(uid) : null;
  let kind = c ? c.kind : (ContactsPage.kind || "usta");
  const seg = el("div.seg");
  const drawSeg = () => {
    seg.innerHTML = "";
    for (const [k, l] of [["usta", t("🔧  Usta")], ["dukkan", t("🏪  Dükkan")]]) {
      seg.append(el("button" + (kind === k ? ".on" : ""), { text: l, onclick: () => { kind = k; drawSeg(); if (typeof showIcon === "function") showIcon(); } }));
    }
  };
  drawSeg();
  const name = el("input.in", { value: c ? c.name : "", placeholder: t("Örn. Ahmet Usta / Yıldız Hırdavat") });
  const prof = el("input.in", { value: c ? c.profession : "", placeholder: t("Örn. Elektrikçi, Tesisatçı, Nalbur"), list: "profList" });
  const profs = new Set([...(I18N.professions[I18N.lang] || []), ...Store.professions()]);
  const dl = el("datalist", { id: "profList" }, [...profs].map(p => el("option", { value: p })));
  const place = el("input.in", { value: c ? c.place : "", placeholder: t("Semt, sokak ya da adres") });
  const phone = el("input.in.ltr", { type: "tel", value: c ? c.phone : "", placeholder: t("Örn. 0532 123 45 67 ya da +963 …") });
  const checks = el("div.checks", null, CHANNELS.map(([field, key, label]) => el("label", null, [
    el("input", { type: "checkbox", name: field, checked: c ? !!c[field] : field !== "has_telegram" }),
    el("img", { src: `img/${key}.png`, alt: "" }), t(label)])));
  const notes = el("textarea.in", { placeholder: t("Çalışma saatleri, fiyat, tavsiye eden kişi…") });
  notes.value = c ? c.notes : "";
  const err = el("div.err");
  const pe = photoEditor(c ? (c.photos || []) : []);
  const je = jobsEditor(c ? (c.jobs || []) : []);
  const profIcon = el("span");
  const showIcon = () => { profIcon.innerHTML = ""; profIcon.append(Icons.badge(prof.value.trim(), kind, 46)); };
  let iconTimer;
  prof.addEventListener("input", () => { clearTimeout(iconTimer); iconTimer = setTimeout(showIcon, 300); });
  showIcon();
  let busy = false;
  fullPage({ title: c ? c.name : t("Yeni usta / dükkan"),
    onSave: async close => {
      if (busy) return;
      if (!name.value.trim()) { err.textContent = t("Lütfen bir ad yazın"); return; }
      busy = true;
      err.className = "ok";
      err.textContent = t("Kaydediliyor…");
      const v = { kind, name: name.value, profession: prof.value, place: place.value, phone: phone.value, notes: notes.value, jobs: je.value() };
      for (const i of checks.querySelectorAll("input")) v[i.name] = i.checked;
      await Store.saveContact(v, uid, await pe.commit());
      if (v.profession.trim()) Icons.fetch(v.profession.trim());
      Cloud.soon();
      close();
      toast(t("Kaydedildi"));
      App.render();
    },
    build: () => el("div", null, [
      el("label.f", { text: t("Tür:") }), seg,
      el("label.f", { text: t("İsim:") }), name,
      el("label.f", { text: t("Meslek / alan:") }), el("div.hrow", null, [profIcon, el("div.grow", null, prof)]), dl,
      el("div.hint", { text: t("Yeni bir meslek yazarsanız uygun simge internetten kendiliğinden bulunur.") }),
      el("label.f", { text: t("Yer / adres:") }), place,
      el("label.f", { text: t("Telefon:") }), phone,
      el("label.f", { text: t("Ulaşılabilir:") }), checks,
      el("div.hint", { text: t("Numaranın hangi uygulamalarda çalıştığını işaretleyin.") }),
      el("label.f", { text: t("Notlar:") }), notes,
      je.node,
      pe.node, err,
    ]) });
}

// ====================================================================== ayarlar
/** '📦   Eşyalarım:' → ['📦   ', 'Eşyalarım', ':'] */
function labelSplit(s) {
  const m = /^([^\p{L}\p{N}_]*)([\s\S]*?)([:：…]?\s*)$/u.exec(s || "");
  return m ? [m[1], m[2], m[3]] : ["", s || "", ""];
}
/** Bir etiket değişince aynı yazının simgeli / iki noktalı öbür biçimleri de değişir (masaüstü labels.propagate ile aynı). */
function labelPropagate(keys, base, values, key, nv) {
  const [, ck] = labelSplit(base(key));
  const cv = nv ? labelSplit(nv)[1] : "";
  if (nv) values[key] = nv;
  for (const j of keys) {
    if (j === key) continue;
    const [pj, cj, sj] = labelSplit(base(j));
    if (!ck || cj !== ck) continue;
    if (nv) values[j] = pj + cv + sj; else delete values[j];
  }
  if (!nv) delete values[key];
}

/** Ayarlar → Etiketler: her yazıya dokununca yeni etiket yazılır; kapanınca ekran yeni yazılarla çizilir. */
function labelEditor() {
  const lang = I18N.lang;
  const read = () => { try { const d = JSON.parse(Store.get("labels_v1", "{}") || "{}"); return d && typeof d === "object" ? d : {}; } catch (e) { return {}; } };
  const keys = Object.keys(I18N.strings);
  for (const k of Object.keys(I18N.overrides[lang] || {})) if (!keys.includes(k)) keys.push(k);
  const norm = s => String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");
  let changed = false;
  const save = async map => {
    const d = read();
    if (Object.keys(map).length) d[lang] = map; else delete d[lang];
    await Store.set("labels_v1", JSON.stringify(d));
    I18N.setOverrides(d);
    changed = true;
  };
  fullPage({ title: t("Etiketleri düzenle"), onClose: () => { if (changed) App.render(); }, build: () => {
    const box = el("div");
    const search = el("input.in", { type: "search", placeholder: t("Etiket ara…") });
    const only = el("input", { type: "checkbox" });
    const list = el("div.tree.card", { style: { padding: "4px 8px" } });
    const draw = () => {
      list.innerHTML = "";
      const q = norm(search.value.trim()), cur = I18N.overrides[lang] || {};
      let shown = 0;
      for (const k of keys) {
        const base = baseText(k, lang), mine = cur[k] || "";
        if (only.checked && !mine) continue;
        if (q && !norm(base + " " + mine + " " + k).includes(q)) continue;
        if (++shown > 400) break;
        list.append(el("div.node", { onclick: async () => {
          const v = await ask(base + "\n\n" + t("Yeni etiket (boş = programın yazısı):"), { input: true, value: mine || base, yes: t("Kaydet") });
          if (v === null && !mine) return;
          const m = Object.assign({}, I18N.overrides[lang] || {});
          labelPropagate(keys, x => baseText(x, lang), m, k, v && v !== base ? v : "");
          for (const x of Object.keys(m)) if (!m[x] || m[x] === baseText(x, lang)) delete m[x];
          await save(m); draw();
        } }, [
          el("span.n", null, [el("div", { text: base, style: mine ? { textDecoration: "line-through", color: "var(--muted)", fontSize: "12px" } : null }),
            mine ? el("div", { text: mine, style: { fontWeight: "700", color: "var(--teal-dark)" } }) : null]),
          el("button.dots", { text: "✎" }),
        ]));
      }
      if (!shown) list.append(el("div.empty", { text: "—" }));
    };
    search.addEventListener("input", draw);
    only.addEventListener("change", draw);
    box.append(el("div.hint", { style: { marginBottom: "10px", whiteSpace: "pre-line" },
      text: t("Programdaki bütün yazıları (düğmeler, başlıklar, alan adları) kendinize göre değiştirebilirsiniz. Değişiklik yalnızca seçili dil için geçerlidir.") + "\n" + t("{x} gibi yer tutucuları silmeyin; oraya sayı ya da ad gelir.") }));
    box.append(search);
    box.append(el("label", { style: { display: "flex", alignItems: "center", gap: "8px", margin: "10px 2px" } }, [only, t("Yalnızca değiştirilenler")]));
    box.append(list);
    box.append(el("button.btn.danger.block", { text: t("Hepsini sıfırla"), style: { marginTop: "12px" }, onclick: async () => {
      if (await ask(t("Bütün etiketler programın kendi yazısına dönsün mü?"), { yes: t("Hepsini sıfırla"), danger: true })) { await save({}); draw(); }
    } }));
    draw();
    return box;
  } });
}

function treeEditor(table) {
  const title = table === "locations" ? t("🏠  Yerler") : t("🗂  Kategoriler");
  fullPage({ title, build: () => {
    const box = el("div");
    const draw = () => {
      box.innerHTML = "";
      const counts = Store.itemCounts(table);
      const tree = el("div.tree.card", { style: { padding: "4px 8px" } });
      const nodes = Store.treeOrdered(table);
      for (const n of nodes) {
        const c = counts.get(n.uid) || 0;
        tree.append(el("div.node", { style: { paddingInlineStart: (8 + n.depth * 22) + "px" }, onclick: () => actions(n) }, [
          el("span.n", { text: (n.depth ? "└ " : "") + n.name }),
          c ? el("span.c", { text: t("{n} eşya", { n: c }) }) : null,
          el("button.dots", { text: "⋮" }),
        ]));
      }
      if (!nodes.length) tree.append(el("div.empty", { text: "—" }));
      box.append(el("div.hint", { style: { marginBottom: "10px" } }, t("Bir öğeye dokunarak alt öğe ekleyebilir, adını değiştirebilir, sırasını ya da yerini değiştirebilir veya silebilirsiniz.")));
      box.append(tree);
      box.append(el("button.btn.primary.block", { text: t("＋ Ekle"), onclick: async () => { if (await newNodeDialog(table, "")) draw(); } }));
    };
    const actions = n => menu(n.path, [
      [t("＋ Alt öğe ekle"), async () => { if (await newNodeDialog(table, n.uid)) draw(); }],
      [t("✎ Yeniden adlandır"), async () => {
        const v = await ask(t("Yeni ad:"), { input: true, value: n.name, yes: t("Kaydet") });
        if (v) { await Store.renameNode(table, n.uid, v); Cloud.soon(); draw(); }
      }],
      [t("▲  Yukarı taşı"), async () => { await Store.moveNode(table, n.uid, -1); Cloud.soon(); draw(); }],
      [t("▼  Aşağı taşı"), async () => { await Store.moveNode(table, n.uid, 1); Cloud.soon(); draw(); }],
      [t("↪  Başka bir öğenin altına taşı"), async () => {
        const v = await pickNode(table, n.parent, { add: false, none: true, exclude: n.uid,
          title: table === "locations" ? t("Üst yer:") : t("Üst kategori:") });
        if (v !== undefined) { await Store.setParent(table, n.uid, v || ""); Cloud.soon(); draw(); }
      }],
      [t("Sil"), async () => {
        const hasKids = Store.treeRows(table).some(r => r.parent === n.uid);
        let text = hasKids ? t("„{name}“ ve altındaki her şey silinsin mi?\n", { name: n.name }) : t("„{name}“ silinsin mi?\n", { name: n.name });
        const k = Store.itemsUnder(table, n.uid);
        if (k) text += t("\nBurada kayıtlı {n} eşya silinmeyecek; bir üst öğeye taşınacak.", { n: k });
        if (await ask(text, { yes: t("Sil"), danger: true })) { await Store.deleteNode(table, n.uid); Cloud.soon(); draw(); }
      }, true],
    ]);
    draw();
    return box;
  }, onClose: () => App.render() });
}

function accountForm() {
  const config = el("textarea.in.ltr", { placeholder: 'const firebaseConfig = {\n  apiKey: "…",\n  projectId: "…",\n  …\n};', style: { minHeight: "130px", fontSize: "13px" } });
  config.value = Store.get("fb_config", "") || DEFAULT_FB_CONFIG;
  const email = el("input.in.ltr", { type: "email", value: Cloud.email(), placeholder: "ornek@gmail.com", autocomplete: "username" });
  const pw = el("input.in.ltr", { type: "password", autocomplete: "current-password" });
  const msg = el("div.err");
  const go = async (create, close) => {
    if (!email.value.trim() || !pw.value) { msg.className = "err"; msg.textContent = t("E-posta ve şifreyi yazın."); return; }
    msg.className = "ok";
    msg.textContent = t("Bağlanıyor…");
    try {
      await Cloud.connect(config.value, email.value, pw.value, create);
    } catch (e) {
      msg.className = "err";
      msg.textContent = e instanceof SyncError ? syncErrorText(e) : String(e);
      return;
    }
    close();
    toast(t("Bulut hesabı bağlandı"));
    Cloud.syncNow();
  };
  fullPage({ title: t("Bulut hesabı (Firebase)"), build: close => el("div", null, [
    el("div.hint", { text: t("Telefon ve bilgisayarda aynı Firebase ayarlarını ve aynı e-posta/şifreyi kullanın. Böylece iki cihaz aynı arşivi görür.") }),
    el("div.hint", { text: t("Eşitleme kendi ücretsiz Firebase hesabınızla yapılır; kayıtlarınız ve günlük sınırınız yalnızca size aittir.") }),
    el("button.btn.block", { text: t("Kendi Firebase hesabınızı kurun (rehber)"), onclick: () => openUrl(FB_REHBER) }),
    el("label.f", { text: t("Firebase ayarları:") }), config,
    el("div.hint", { text: t("Firebase konsolunda Proje ayarları › Uygulamalarınız › firebaseConfig bölümünü kopyalayıp buraya yapıştırın.") }),
    el("label.f", { text: t("E-posta:") }), email,
    el("label.f", { text: t("Şifre:") }), pw,
    msg,
    el("button.btn.primary.block", { text: t("Giriş yap"), onclick: () => go(false, close) }),
    el("button.btn.block", { text: t("Yeni hesap oluştur"), onclick: () => go(true, close) }),
  ]) });
}

async function backup() {
  toast(t("Yedek hazırlanıyor…"));
  const json = await Store.exportAll();
  const d = new Date();
  const name = `Organizer-yedek-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}.json`;
  if (Native && Native.shareFile) {
    Native.shareFile(name, "application/json", btoa(unescape(encodeURIComponent(json))));
  } else {
    const a = el("a", { href: URL.createObjectURL(new Blob([json], { type: "application/json" })), download: name });
    document.body.append(a); a.click(); a.remove();
  }
}

const SettingsPage = {
  render(root) {
    root.append(el("div.pagetitle", { text: t("Ayarlar") }));
    const cards = [];   // 2.2.0: kartlar ortak çekirdeğin ayar ızgarasına girer (Görünüm başta, Admin ile iletişim EN SONDA)
    const cur = el("select.in", { onchange: () => Store.set("default_currency", cur.value) },
      CURRENCIES.map(([c, sym, n]) => el("option", { value: c, text: `${sym}  ${t(n)}` })));
    cur.value = Store.get("default_currency", "TRY");
    const cc = el("input.in.ltr", { type: "tel", value: Store.get("country_code", "90"), style: { width: "110px" } });
    cc.addEventListener("change", () => { const v = cc.value.replace(/\D/g, "") || "90"; cc.value = v; Store.set("country_code", v); });
    cards.push(el("div.card.section", null, [
      el("h3", { text: t("⚙  Genel") }),
      el("label.f", { text: t("Varsayılan para birimi:") }), cur,
      el("label.f", { text: t("Ülke telefon kodu:") }), cc,
      el("div.hint", { text: t("WhatsApp / Telegram bağlantıları için kullanılır. Numara + ile yazılmışsa kendi kodu geçerlidir.") }),
    ]));
    const nLab = Object.keys(I18N.overrides[I18N.lang] || {}).length;
    cards.push(el("div.card.section", null, [
      el("h3", { text: t("🏷  Etiketler") }),
      el("div.hint", { text: t("Programdaki bütün yazıları (düğmeler, başlıklar, alan adları) kendinize göre değiştirebilirsiniz. Değişiklik yalnızca seçili dil için geçerlidir.") }),
      nLab ? el("div.hint", { text: t("{n} etiket değiştirildi", { n: nLab }) }) : null,
      el("button.btn.block", { text: t("🏷  Etiketleri düzenle…"), style: { textAlign: "start", marginTop: "8px" }, onclick: labelEditor }),
    ]));
    const nLoc = Store.treeRows("locations").length, nCat = Store.treeRows("categories").length;
    cards.push(el("div.card.section", null, [
      el("h3", { text: t("Sınıflandırma") }),
      el("button.btn.block", { text: `${t("🏠  Yerler")}  (${nLoc})`, style: { textAlign: "start" }, onclick: () => treeEditor("locations") }),
      el("button.btn.block", { text: `${t("🗂  Kategoriler")}  (${nCat})`, style: { textAlign: "start" }, onclick: () => treeEditor("categories") }),
    ]));
    const status = el("div.hint");
    const sync = el("button.btn.primary.grow", { text: t("⟳  Şimdi eşitle"), onclick: () => Cloud.syncNow() });
    const acc = el("button.btn.grow");
    const draw = () => {
      const on = Cloud.isConnected();
      status.textContent = (on ? t("Bağlı hesap: {e}", { e: Cloud.email() }) + "\n" : "") + Cloud.statusText();
      status.style.whiteSpace = "pre-line";
      acc.textContent = on ? t("🔌  Hesabı kaldır") : t("🔑  Hesaba bağlan");
      sync.disabled = !on || Cloud.busy;
    };
    acc.onclick = async () => {
      if (!Cloud.isConnected()) return accountForm();
      if (await ask(t("Bu telefon bulut hesabından ayrılsın mı?\nTelefondaki kayıtlar silinmez."), { yes: t("Hesabı kaldır"), danger: true })) Cloud.disconnect();
    };
    this.cloudDraw = draw;
    draw();
    cards.push(el("div.card.section", null, [
      el("h3", { text: t("☁  Bulut hesabı (Firebase)") }), status,
      el("div.hrow", { style: { marginTop: "10px" } }, [acc, sync]),
    ]));
    // ---- v.1.0.8: internet yokken aynı modem / Wi-Fi üzerinden bilgisayarla eşitleme
    const lanStatus = el("div.hint", { style: { whiteSpace: "pre-line" } });
    const lanBtns = el("div");
    const lanDraw = () => {
      lanStatus.textContent = Lan.status();
      lanBtns.innerHTML = "";
      if (!Lan.available()) {
        lanBtns.append(el("div.hint", { text: t("Bu özellik için uygulamanın yeni sürümü gerekir. Üstteki güncelleme düğmesine dokunun.") }));
        return;
      }
      const peer = Lan.peer();
      if (peer) lanBtns.append(el("button.btn.primary.block", { text: t("⟳  Şimdi eşitle: {x}", { x: Store.get("lan_peer_name", peer.split(":")[0]) }),
        disabled: Lan.busy, onclick: () => Lan.run() }));
      lanBtns.append(el("button.btn.block" + (peer ? "" : ".primary"), { text: t("🔍  Bilgisayarı bul ve eşitle"), disabled: Lan.busy, onclick: () => Lan.findAndSync() }));
      lanBtns.append(el("button.btn.block", { text: t("Adresi elle yaz…"), disabled: Lan.busy, onclick: () => Lan.manual() }));
    };
    this.lanDraw = lanDraw;
    lanDraw();
    cards.push(el("div.card.section#lanCard", null, [
      el("h3", { text: t("📶  Yerel ağ eşitlemesi (internetsiz)") }),
      el("div.hint", { text: t("İnternet olmadığında telefon ve bilgisayarlar aynı modem / Wi-Fi üzerinden eşitlenir. Kayıtlar bulut eşitlemesindeki gibi birleştirilir: her kaydın en son değiştirilen hali kalır, hiçbir şey silinmez ya da üst üste yazılmaz. İnternet gelince değişiklikler buluta da gider.") }),
      el("div.hint", { text: t("Bilgisayarda Organizer açık olmalı. İlk seferde bilgisayarın Ayarlar sayfasındaki 6 haneli eşleme kodu sorulur (iki cihaz aynı bulut hesabındaysa sorulmaz).") }),
      lanStatus, lanBtns,
    ]));
    cards.push(el("div.card.section", null, [
      el("h3", { text: t("Veriler ve yedek") }),
      el("div.hint", { text: t("Kayıtlar ve fotoğraflar bu telefonda saklanır. Bulut hesabı bağlıysa bilgisayarla da eşitlenir.") }),
      el("button.btn.block", { text: t("💾  Yedek al (.json) ve paylaş"), onclick: backup }),
      el("button.btn.block", { text: t("🗑 Çöp kutusu ({n})", { n: Store.trashItemsList().length }), onclick: trashPage }),
    ]));
    cards.push(Kabuk.arsivKarti());
    // Görünüm (tema, şema, yazı boyutu, dil) · uygulama kartları · Asistan Agent · Kullanım Limitleri · Otomatik hata raporu ·
    // Hakkında (güncelleme) · Admin ile iletişim (EN SON)
    Kabuk.ayarlar(root, cards);
    root.append(el("div.about", null, [el("img", { src: "img/logo.png", alt: "" }), el("div", { text: `Organizer ${goster()}` }),
      el("div", { text: t("Evdeki her şey yerli yerinde") })]));
  },
};

// ====================================================================== üst çubuk (sağ üst köşe)
const TB_ICONS = {
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1"/><path d="M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M7 12h10"/>',
  lang: '<path d="M4 5h9M8.5 3v2M11 5c-1 4-3.6 7-7 8.5"/><path d="M6 8.5c1.3 2 3 3.4 5 4.3"/><path d="M13 21l4-9 4 9M14.4 18h5.2"/>',
  sync: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>',
  cloud: '<path d="M7 18a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 8.6 4.7 4.7 0 0 1 17.5 18z"/>',
  download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
};
function svgIcon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${TB_ICONS[name]}</svg>`;
}

const TopBar = {
  // 2.2.0: üst çubuk ortak çekirdekten (kabuk.js → FC.topbar.mount): Fiyatları gizle · Hızlı ara · Duyurular · Eşitle · Wi‑Fi ·
  // Güncelle · Tema · Dil | Kapat
  init() { Kabuk.ustCubuk(); },
  draw() { Kabuk.ciz(); },
  drawUpdate() {},
};

// ====================================================================== uygulama
const App = {
  tab: 0,
  pages: [ItemsPage, ContactsPage, SettingsPage],

  async start() {
    await Store.open();
    I18N.setLanguage(Store.get("language", "tr"));
    I18N.setOverrides(Store.get("labels_v1", "{}"));
    await Store.seed(I18N.lang);
    Kabuk.baslat();   // ortak çekirdek: görünüm, dil, güncelleme, duyurular, ilk açılış rehberi, çökme raporu
    await Icons.init();
    await Icons.warm();
    PhotoInput.init();
    Theme.apply();
    try { if (await Store.purgeOldTrash()) Cloud.soon(); } catch (e) { /* çöp temizliği açılışı engellemesin */ }
    PRICES_HIDDEN = Store.get("prices_hidden", "0") === "1";
    if (!Store.get("price_auto_v1", null)) {
      // bir kerelik: eşyaları buluttan yeniden al ki otomatik fiyat işaretleri (⚡) gelsin
      await Store.set("sync_cursor_items", null);
      await Store.set("price_auto_v1", "1");
    }
    TopBar.init();
    Cloud.listeners.push(text => this.syncState(text));
    Store.listeners.push(what => { if (what === "sync") this.render(true); });
    this.render();
    this.syncState(Cloud.statusText());
    const lanQuiet = () => { if (!Cloud.isConnected() && Lan.peer() && Lan.available()) Lan.run({ quiet: true }); };
    if (Cloud.isConnected()) Cloud.syncNow(); else setTimeout(lanQuiet, 1500);
    setInterval(() => { if (document.visibilityState === "visible") { Cloud.syncNow(); lanQuiet(); } }, 3 * 60 * 1000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") Cloud.soon(800);
      else if (Object.values(Store.dirtyRecords()).some(a => a.length) || Store.photosToUpload().length) Cloud.syncNow();
    });
    window.onBack = () => this.back();
    if (Native && Native.bootOk) Native.bootOk();   // açılış sağlam (eski web paketi düzeninin geri dönüş işareti)
  },

  back() {
    if (Layers.top()) { Layers.close(); return true; }
    if (this.tab === 0 && ItemsPage.sel.size) { ItemsPage.clearSel(); return true; }
    if (this.tab !== 0) { this.tab = 0; this.render(); return true; }
    return false;
  },

  render(keepScroll) {
    document.documentElement.lang = I18N.lang;
    document.documentElement.dir = I18N.rtl ? "rtl" : "ltr";
    $("#appTitle").textContent = "Organizer";
    $("#appSub").textContent = t("Evdeki her şey yerli yerinde");
    $("#verBadge").textContent = "v" + APP_VERSION;
    TopBar.draw();
    const y = window.scrollY;
    const tabs = $("#tabs");
    tabs.innerHTML = "";
    [["📦", t("Eşyalarım")], ["🔧", t("Ustalar")], ["⚙", t("Ayarlar")]].forEach(([icon, label], i) => {
      tabs.append(el("button" + (i === this.tab ? ".on" : ""), { onclick: () => {
        if (this.tab !== i) { this.tab = i; this.render(); window.scrollTo(0, 0); }
      } }, [el("b", { text: icon }), label]));
    });
    const page = $("#page");
    page.innerHTML = "";
    const old = $(".selbar");
    if (old) old.remove();
    this.pages[this.tab].render(page);
    if (keepScroll) window.scrollTo(0, y);
  },

  syncState(text) {
    Kabuk.esitleme(text);
    if (this.tab === 2 && SettingsPage.cloudDraw) SettingsPage.cloudDraw();
  },

  /** Üst çubuktaki Eşitle: bulut bağlıysa bulut, yoksa yerel ağdaki bilgisayar, o da yoksa hesap formu */
  syncClick() {
    if (Cloud.isConnected()) { Cloud.syncNow(); toast(Cloud.statusText()); }
    else if (Lan.peer() && Lan.available()) Lan.run();
    else { this.tab = 2; this.render(); accountForm(); }
  },

  /** Dil değişimi yalnız ortak çekirdekten gelir (üst çubuk / Görünüm kartı → FC.i18n.onChange). */
  async changeLanguage(lang) {
    const old = I18N.lang;
    if (lang === old) return;
    await Store.set("language", lang);
    await Store.translateDefaults(old, lang);
    I18N.setLanguage(lang);
    this.render();
  },
};

window.addEventListener("DOMContentLoaded", () => App.start().catch(e => {
  document.body.innerHTML = `<pre style="padding:20px;white-space:pre-wrap">${esc(e && e.stack || e)}</pre>`;
}));
