/* Organizer 2.3.0 — telefon ekleri (masaüstündeki filtre.py, zeka.py, ceviri.py, disa_aktar.py, yedek.py, panel_page.py karşılığı):
   değişiklik geçmişi · garanti / son kullanma · gelişmiş + kayıtlı filtre · Ana sayfa paneli · Excel / CSV / sigorta envanteri ·
   otomatik + şifreli yedek ve geri yükleme · çeviri (çevrim içi / çevrim dışı sözlük) · Asistan ve fotoğraftan doldurma (yapay zeka). */
"use strict";

const WARN_DAYS = 30;
const CHANGELOG_MAX = 40;
const TRACKED = ["name", "quantity", "category", "location", "price", "currency", "notes", "shop_name", "shop_place", "shop_phone",
  "min_qty", "to_buy", "loan_to", "loan_due", "trashed_at", "warranty_until", "expires_on", "photos", "price_auto"];

function warnDays() { return Math.max(1, parseInt(Store.get("warn_days", String(WARN_DAYS)), 10) || WARN_DAYS); }
function deviceName() { return String(Store.get("device_name", "") || "").trim() || t("Telefon") || "Telefon"; }

// ====================================================================== tarih durumu
function daysLeft(day) {
  if (!/^\d{4}-\d\d-\d\d/.test(String(day || ""))) return null;
  return Math.round((new Date(String(day).slice(0, 10)) - new Date(todayStr())) / 86400000);
}
function dayStatus(day, days) {
  const n = daysLeft(day);
  if (n === null) return null;
  if (n < 0) return "over";
  return n <= (days || warnDays()) ? "soon" : "ok";
}
function dayStatusText(day) {
  const n = daysLeft(day);
  if (n === null) return "";
  if (n < 0) return t("⛔ {n} gün önce bitti", { n: -n });
  if (n === 0) return t("⚠ bugün bitiyor");
  return n <= warnDays() ? t("⚠ {n} gün kaldı", { n }) : t("{n} gün kaldı", { n });
}
function reminders(items, days) {
  days = days || warnDays();
  const out = [];
  for (const d of items) for (const [kind, f] of [["warranty", "warranty_until"], ["expiry", "expires_on"]]) {
    const st = dayStatus(d[f], days);
    if (st !== "soon" && st !== "over") continue;
    const n = daysLeft(d[f]);
    if (kind === "warranty" && n < -days) continue;
    out.push([d, kind, n]);
  }
  return out.sort((a, b) => a[2] - b[2]);
}

// ====================================================================== değişiklik geçmişi
function shortVal(v) {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "1" : "0";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  if (Array.isArray(v)) return String(v.length);
  return String(v).replace(/\n/g, " ").trim().slice(0, 80);
}
function mergeChangelog(a, b) {
  const seen = new Set(), out = [];
  for (const e of [...(a || []), ...(b || [])].filter(e => e && typeof e === "object").sort((x, y) => String(x.t || "").localeCompare(String(y.t || "")))) {
    const k = JSON.stringify([e.t, e.d, e.a || "", e.c || []]);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(e);
  }
  return out.slice(-CHANGELOG_MAX);
}
function trackedState(r) {
  if (!r) return null;
  const c = Store.treePaths("categories"), l = Store.treePaths("locations");
  const s = {};
  for (const f of TRACKED) s[f] = f === "photos" ? (r.photos || []) : r[f];
  s.category = c.get(r.category) || "";
  s.location = l.get(r.location) || "";
  return s;
}
function withLog(old, rec, forced) {
  const base = mergeChangelog(old ? old.changelog : [], rec.changelog);
  const e = { t: nowUtc(), d: deviceName(), c: [] };
  const who = typeof Cloud !== "undefined" && Cloud.email ? Cloud.email() : "";
  if (who) e.u = who;
  if (!old) {
    e.a = "eklendi";
  } else {
    const a = trackedState(old), b = trackedState(rec);
    for (const f of TRACKED) if (shortVal(a[f]) !== shortVal(b[f])) e.c.push([f, shortVal(a[f]), shortVal(b[f])]);
    if (!old.trashed_at && rec.trashed_at) e.a = "silindi";
    else if (old.trashed_at && !rec.trashed_at) e.a = "geri_yuklendi";
    if (forced) e.a = forced;
    if (!e.c.length && !e.a) return { ...rec, changelog: base };
  }
  return { ...rec, changelog: mergeChangelog(base, [e]) };
}
(function hookStore() {
  const save = Store.save.bind(Store), apply = Store.applyRemote.bind(Store), undo = Store.restoreSnapshot.bind(Store);
  Store.save = async function (table, recs) {
    if (table === "items" && !this._applying) {
      recs = (Array.isArray(recs) ? recs : [recs]).map(r => withLog(this.t.items.get(r.uid), r, this._action));
    }
    return save(table, recs);
  };
  Store.applyRemote = async function (table, records, keepDirty) {
    if (table === "items") {   // iki cihazın geçmişi birleşir; bilmeyen eski sürümden gelen kayıtta yereldeki kalır (ITEM_EXTRA)
      records = records.map(rec => {
        const cur = this.t.items.get(rec.uid);
        return cur && Array.isArray(rec.changelog) ? { ...rec, changelog: mergeChangelog(cur.changelog, rec.changelog) } : rec;
      });
    }
    this._applying = true;
    try { return await apply(table, records, keepDirty); } finally { this._applying = false; }
  };
  Store.restoreSnapshot = async function (snap) {
    // geri al: geçmiş geri sarılmaz, "geri alındı" olarak eklenir
    snap = snap.map(r => { const cur = this.t.items.get(r.uid); return cur ? { ...r, changelog: cur.changelog } : r; });
    this._action = "geri_alindi";
    try { return await undo(snap); } finally { this._action = null; }
  };
})();

const FIELD_NAMES = { name: "Adı", quantity: "Adet", category: "Kategori", location: "Yer", price: "Fiyat", currency: "Para birimi",
  notes: "Notlar", shop_name: "Dükkan/Kişi Adı", shop_place: "Dükkan/Kişi Yeri", shop_phone: "İletişim numarası", min_qty: "En az adet",
  to_buy: "Alışveriş listesi", loan_to: "Ödünç", loan_due: "Dönüş günü", trashed_at: "Çöp kutusu", warranty_until: "Garanti bitişi",
  expires_on: "Son kullanma tarihi", photos: "Fotoğraf", price_auto: "Otomatik fiyat" };
const ACTIONS = { eklendi: "➕ Eklendi", silindi: "🗑 Çöp kutusuna taşındı", geri_yuklendi: "↩ Çöp kutusundan geri yüklendi",
  geri_alindi: "↶ Geri alındı", yedekten: "💾 Yedekten geri yüklendi" };
function fmtTs(iso) {
  const d = new Date(iso);
  return isNaN(d) ? String(iso || "") : `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function entryLines(e) {
  const head = `${fmtTs(e.t)} — ${e.d || "?"}${e.u ? " · " + e.u : ""}`;
  const lines = [];
  if (ACTIONS[e.a]) lines.push(t(ACTIONS[e.a]));
  for (let [f, a, b] of e.c || []) {
    const name = t(FIELD_NAMES[f] || f);
    if (f === "to_buy" || f === "price_auto") { a = a === "1" ? t("evet") : t("hayır"); b = b === "1" ? t("evet") : t("hayır"); }
    else if (f === "trashed_at") { if (e.a === "silindi" || e.a === "geri_yuklendi") continue; a = a ? t("evet") : t("hayır"); b = b ? t("evet") : t("hayır"); }
    else if (f === "photos") { lines.push(t("{f}: {a} → {b} adet", { f: name, a: a || "0", b: b || "0" })); continue; }
    else if (["warranty_until", "expires_on", "loan_due"].includes(f)) { a = a ? fmtDay(a) : ""; b = b ? fmtDay(b) : ""; }
    lines.push(`${name}: ${a || "—"} → ${b || "—"}`);
  }
  return [head, lines];
}
function historyPage(uid) {
  const d = Store.t.items.get(uid);
  fullPage({ title: t("Değişiklik geçmişi — {x}", { x: d ? d.name : "" }), build: () => {
    const log = [...((d && d.changelog) || [])].reverse();
    return el("div", null, [
      el("div.hint", { text: t("Kim, hangi cihazdan, ne zaman neyi değiştirdi. Cihazlar arasında eşitlenir (son {n} değişiklik).", { n: CHANGELOG_MAX }) }),
      !log.length ? el("div.empty", { text: t("Bu eşya için henüz kayıtlı değişiklik yok (2.3.0 sürümünden önceki değişiklikler tutulmuyordu).") }) : null,
      ...log.map(e => { const [h, lines] = entryLines(e); return el("div.card.histrow", null, [el("b", { text: h }), ...lines.map(x => el("div", { text: "• " + x }))]); }),
    ]);
  } });
}

// ====================================================================== gelişmiş filtre
const FLAGS = [["photo", "Fotoğrafı olanlar"], ["nophoto", "Fotoğrafı olmayanlar"], ["receipt", "Faturası / fişi olanlar"],
  ["noprice", "Fiyatı girilmemiş"], ["loan", "Ödünçtekiler"], ["late", "Ödünç dönüşü gecikenler"], ["low", "Az kalanlar"],
  ["tobuy", "Alışveriş listesindekiler"], ["warranty", "Garantisi devam edenler"], ["warranty_soon", "Garantisi yakında bitecekler"],
  ["warranty_over", "Garantisi bitmiş olanlar"], ["exp_soon", "Son kullanma tarihi yaklaşanlar"], ["expired", "Son kullanma tarihi geçmiş olanlar"]];
function cleanFilter(f) {
  f = f || {};
  const num = (v, int) => (v === null || v === undefined || v === "" || isNaN(Number(v)) ? null : (int ? parseInt(v, 10) : Number(v)));
  const known = new Set(FLAGS.map(x => x[0]));
  return { price_min: num(f.price_min), price_max: num(f.price_max), currency: String(f.currency || ""), qty_min: num(f.qty_min, true),
    qty_max: num(f.qty_max, true), date_from: String(f.date_from || ""), date_to: String(f.date_to || ""), shop: String(f.shop || "").trim(),
    flags: (f.flags || []).filter(x => known.has(x)) };
}
function filterCount(f) {
  f = cleanFilter(f);
  let n = ["currency", "date_from", "date_to", "shop"].filter(k => f[k]).length;
  n += (f.price_min !== null || f.price_max !== null) + (f.qty_min !== null || f.qty_max !== null);
  return n + f.flags.length;
}
function matchFilter(d, f) {
  const p = d.price;
  if (f.currency && (p == null || d.currency !== f.currency)) return false;
  if (f.price_min !== null && (p == null || p < f.price_min)) return false;
  if (f.price_max !== null && (p == null || p > f.price_max)) return false;
  const q = d.quantity || 0;
  if (f.qty_min !== null && q < f.qty_min) return false;
  if (f.qty_max !== null && q > f.qty_max) return false;
  const c = String(d.created_at || "").slice(0, 10);
  if (f.date_from && c < f.date_from) return false;
  if (f.date_to && c > f.date_to) return false;
  if (f.shop) {
    const hay = norm([d.shop_name, d.shop_place, d.shop_phone].join(" "));
    if (!norm(f.shop).split(/\s+/).filter(Boolean).every(x => termIn(x, hay))) return false;
  }
  const photos = d.photos || [], np = photos.filter(x => !isReceipt(x)).length, nr = photos.length - np;
  const w = dayStatus(d.warranty_until), e = dayStatus(d.expires_on);
  const late = !!d.loan_to && overdueDays(d) > 0;
  const chk = { photo: np > 0, nophoto: np === 0, receipt: nr > 0, noprice: p == null, loan: !!d.loan_to, late, low: isLow(d),
    tobuy: !!d.to_buy || isLow(d), warranty: w === "ok" || w === "soon", warranty_soon: w === "soon", warranty_over: w === "over",
    exp_soon: e === "soon", expired: e === "over" };
  return f.flags.every(k => chk[k] !== false);
}
function applyFilter(items, f) {
  f = cleanFilter(f);
  return filterCount(f) ? items.filter(d => matchFilter(d, f)) : items;
}
function savedFilters() { try { return (JSON.parse(Store.get("saved_filters_v1", "[]")) || []).filter(x => x && x.name); } catch (e) { return []; } }
async function saveFilter(name, f) {
  const list = savedFilters().filter(x => x.name !== name);
  list.push({ name: String(name).slice(0, 60), f: cleanFilter(f) });
  await Store.set("saved_filters_v1", JSON.stringify(list.slice(-30)));
}

function filterPage() {
  const f = cleanFilter(ItemsPage.adv);
  const inp = (v, attrs) => el("input.in", { type: "number", inputmode: "decimal", value: v === null ? "" : v, ...attrs });
  const pmin = inp(f.price_min, { placeholder: "min" }), pmax = inp(f.price_max, { placeholder: "max" });
  const qmin = inp(f.qty_min, { placeholder: "min", inputmode: "numeric" }), qmax = inp(f.qty_max, { placeholder: "max", inputmode: "numeric" });
  const cur = el("select.in", null, [el("option", { value: "", text: t("Hepsi") }), ...CURRENCIES.map(([c, s, n]) => el("option", { value: c, text: `${s}  ${t(n)}` }))]);
  cur.value = f.currency;
  const dfrom = el("input.in", { type: "date", value: f.date_from }), dto = el("input.in", { type: "date", value: f.date_to });
  const shop = el("input.in", { value: f.shop, placeholder: t("Dükkan / kişi adı, yeri ya da numarası") });
  const flags = new Set(f.flags);
  const flagBox = el("div.flaggrid", null, FLAGS.map(([k, label]) => {
    const b = el("button.chip" + (flags.has(k) ? ".on" : ""), { text: t(label), type: "button" });
    b.onclick = () => { if (flags.has(k)) flags.delete(k); else flags.add(k); b.classList.toggle("on", flags.has(k)); };
    return b;
  }));
  const value = () => cleanFilter({ price_min: pmin.value, price_max: pmax.value, currency: cur.value, qty_min: qmin.value, qty_max: qmax.value,
    date_from: dfrom.value, date_to: dto.value, shop: shop.value, flags: [...flags] });
  fullPage({ title: t("Gelişmiş filtre"), saveLabel: t("Uygula"), onSave: close => { ItemsPage.adv = value(); close(); App.render(); },
    build: close => el("div", null, [
      el("label.f", { text: t("Fiyat aralığı:") }), el("div.hrow", null, [pmin, pmax, cur]),
      el("label.f", { text: t("Adet aralığı:") }), el("div.hrow", null, [qmin, qmax]),
      el("label.f", { text: t("Ekleme tarihi:") }), el("div.hrow", null, [dfrom, dto]),
      el("label.f", { text: t("Satın alındığı yer:") }), shop,
      el("label.f", { text: t("Durum") }), flagBox,
      el("div.hint", { text: t("Seçilen bütün koşullar birlikte aranır. Kategori / yer ağacı ve arama kutusu da geçerlidir.") }),
      el("div.hrow", { style: { marginTop: "14px" } }, [
        el("button.btn.grow", { text: t("💾  Filtreyi kaydet…"), onclick: async () => {
          const v = value();
          if (!filterCount(v)) { toast(t("Kaydetmek için önce en az bir koşul seçin.")); return; }
          const name = await ask(t("Filtrenin adı:"), { input: true, yes: t("Kaydet") });
          if (name) { await saveFilter(name, v); toast(t("„{x}“ kaydedildi. „Filtre ▾“ menüsünden tek tıkla açabilirsiniz.", { x: name })); }
        } }),
        el("button.btn", { text: t("Temizle"), onclick: () => { ItemsPage.adv = {}; close(); App.render(); } }),
      ]),
    ]) });
}
function filterMenu() {
  const list = savedFilters();
  menu(t("⚙  Filtre ▾").replace("▾", "").trim(), [
    [t("⚙  Gelişmiş filtre…"), filterPage],
    ...list.map(x => ["★  " + x.name, () => { ItemsPage.adv = cleanFilter(x.f); App.render(); }]),
    list.length ? [t("Kayıtlı filtreyi sil"), () => menu(t("Kayıtlı filtreyi sil"), list.map(x => [x.name, async () => {
      if (await ask(t("„{x}“ filtresi silinsin mi?", { x: x.name }), { yes: t("Sil"), danger: true })) {
        await Store.set("saved_filters_v1", JSON.stringify(savedFilters().filter(y => y.name !== x.name)));
      }
    }, true]))] : null,
    [t("Hızlı filtre"), () => menu(t("Hızlı filtre"), FLAGS.map(([k, l]) => [t(l), () => { ItemsPage.adv = { flags: [k] }; App.render(); }]))],
    filterCount(ItemsPage.adv) ? [t("✕  Gelişmiş filtreyi kaldır"), () => { ItemsPage.adv = {}; App.render(); }, true] : null,
  ]);
}

// ====================================================================== Ana sayfa paneli
const PanelPage = {
  render(root) {
    root.append(el("div.pagetitle", { text: t("Ana sayfa") }));
    const days = warnDays();
    const items = Store.listItems({ sort: "created_desc" });
    const totals = Store.totals(items);
    const order = ["USD", ...CURRENCIES.map(c => c[0]).filter(c => c !== "USD")];
    const value = order.filter(c => c in totals).map(c => fmtPrice(totals[c], c)).join(" + ") || "—";
    const low = items.filter(d => isLow(d) || (d.quantity === 0 && d.min_qty));
    const loans = items.filter(d => d.loan_to), late = loans.filter(d => overdueDays(d) > 0);
    const rem = reminders(items, days);
    const noPrice = items.filter(d => d.price == null).length;
    const go = f => { App.tab = 0; ItemsPage.adv = cleanFilter(f); ItemsPage.search = ""; ItemsPage.cat = ItemsPage.loc = null; App.render(); };
    const tile = (title, val, sub, f) => el("div.card.tile" + (f ? ".link" : ""), { onclick: f ? () => go(f) : null },
      [el("div.tt", { text: title }), el("div.tv", { text: val }), sub ? el("div.ts", { text: sub }) : null]);
    root.append(el("div.tiles", null, [
      tile(t("Eşya"), fmtNum(items.length), t("toplam {q} adet", { q: fmtNum(items.reduce((a, d) => a + d.quantity, 0)) })),
      tile(t("Toplam değer"), value, noPrice ? t("{n} eşyanın fiyatı girilmemiş", { n: noPrice }) : t("Bütün eşyaların fiyatı girilmiş ✓"), noPrice ? { flags: ["noprice"] } : null),
      tile(t("Az kalan / biten"), fmtNum(low.length), t("alışveriş listesine eklendi"), { flags: ["tobuy"] }),
      tile(t("Ödünçte"), fmtNum(loans.length), late.length ? t("⚠ {n} gecikti", { n: late.length }) : "", { flags: ["loan"] }),
      tile(t("Garanti / son kullanma"), fmtNum(rem.length), t("{n} gün içinde biten ya da geçen", { n: days }),
        rem.some(r => r[1] === "warranty") ? { flags: ["warranty_soon", "warranty_over"] } : { flags: ["exp_soon"] }),
    ]));
    const list = (title, rows, empty) => el("div.card.section.panelcard", null, [el("h3", { text: title }),
      !rows.length ? el("div.hint", { text: empty }) : null,
      ...rows.slice(0, 8).map(([uid, name, sub, cls]) => el("button.prow", { onclick: () => itemDetail(uid) },
        [el("b", { text: name }), sub ? el("span" + (cls ? "." + cls : ""), { text: sub }) : null])),
      rows.length > 8 ? el("div.hint", { text: t("… ve {n} eşya daha", { n: rows.length - 8 }) }) : null]);
    root.append(list(t("Garantisi / son kullanması yaklaşanlar"), rem.map(([d, kind, n]) => {
      const f = kind === "warranty" ? d.warranty_until : d.expires_on;
      return [d.uid, d.name, `${kind === "warranty" ? t("Garanti") : t("Son kullanma")}: ${fmtDay(f)} · ${dayStatusText(f)}`, n < 0 ? "latetxt" : "lowtxt"];
    }), t("Önümüzdeki {n} gün içinde biten bir şey yok. ✓", { n: days })));
    root.append(list(t("Az kalanlar"), low.map(d => [d.uid, d.name, t("Adet: {q} · en az {m}", { q: d.quantity, m: d.min_qty }), "lowtxt"]), t("Azalan eşya yok. ✓")));
    root.append(list(t("Ödünçtekiler"), loans.sort((a, b) => overdueDays(b) - overdueDays(a)).map(d => [d.uid, d.name, loanText(d), overdueDays(d) > 0 ? "latetxt" : ""]),
      t("Ödünç verilmiş eşya yok.")));
    root.append(list(t("Son eklenenler"), items.slice(0, 8).map(d => [d.uid, d.name, [fmtDate(d.created_at).split(" ")[0], d.location_path].filter(Boolean).join(" · ")]),
      t("Henüz eşya eklenmemiş.")));
    const changed = items.map(d => [d, (d.changelog || [])[(d.changelog || []).length - 1]]).filter(([, e]) => e && !(e.a === "eklendi" && !(e.c || []).length))
      .sort((a, b) => String(b[1].t).localeCompare(String(a[1].t)))
      .map(([d, e]) => { const [, lines] = entryLines(e); return [d.uid, d.name, `${fmtTs(e.t)} · ${e.d || ""}${lines[0] ? " · " + lines[0] : ""}`]; });
    root.append(list(t("Son değişenler"), changed, t("Henüz kayıtlı değişiklik yok.")));
    const groups = new Map();
    for (const d of items) {
      const top = (d.category_path || t("Belirtilmemiş")).split(" › ")[0];
      const g = groups.get(top) || { n: 0, v: {} };
      g.n++;
      if (d.price != null) g.v[d.currency] = (g.v[d.currency] || 0) + d.price;
      groups.set(top, g);
    }
    const big = Math.max(1, ...[...groups.values()].map(g => g.n));
    root.append(el("div.card.section.panelcard", null, [el("h3", { text: t("Kategoriye göre") }),
      ...[...groups.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 10).map(([name, g]) => el("div.catrow", null, [
        el("div", { text: `${name} · ${g.n} ${t("eşya")}` + (Object.keys(g.v).length ? " · " + order.filter(c => c in g.v).map(c => fmtPrice(g.v[c], c)).join(" + ") : "") }),
        el("div.catbar", { style: { width: Math.max(4, Math.round(100 * g.n / big)) + "%" } })]))]));
  },
};

// ====================================================================== çeviri
const Ceviri = {
  idx: {},
  index(lang) {
    if (!this.idx[lang]) { const i = { tr: 0, en: 1, ar: 2 }[lang]; this.idx[lang] = new Map(SOZLUK.map(w => [norm(w[i]), w])); }
    return this.idx[lang];
  },
  suffixes: ["ındaki", "indeki", "undaki", "ündeki", "ndaki", "ndeki", "daki", "deki", "taki", "teki", "ları", "leri", "ndan", "nden", "dan", "den",
    "tan", "ten", "nda", "nde", "lar", "ler", "nın", "nin", "nun", "nün", "da", "de", "ta", "te", "ın", "in", "un", "ün", "sı", "si", "su", "sü",
    "yı", "yi", "yu", "yü", "ya", "ye", "ı", "i", "u", "ü", "a", "e"],
  stem(w, lang) {
    if (lang === "ar") return w.startsWith("ال") && w.length > 3 ? w.slice(2) : w;
    if (lang !== "tr") return w.endsWith("s") && w.length > 3 ? w.slice(0, -1) : w;
    for (const s of this.suffixes) if (w.endsWith(s) && w.length - s.length >= 3 && this.index("tr").has(w.slice(0, -s.length))) return w.slice(0, -s.length);
    return w;
  },
  detect(text) {
    const s = String(text || "");
    if (/[؀-ۿ]/.test(s)) return "ar";
    if (/[çğışöüÇĞİŞÖÜ]/.test(s)) return "tr";
    const words = norm(s).split(/\s+/).filter(Boolean);
    const tr = words.filter(w => this.index("tr").has(w) || this.index("tr").has(this.stem(w, "tr"))).length;
    const en = words.filter(w => this.index("en").has(w)).length;
    return en > tr ? "en" : "tr";
  },
  offline(text, src, dst) {
    if (src === dst) return text;
    const idx = this.index(src), j = { tr: 0, en: 1, ar: 2 }[dst];
    return String(text).split("\n").map(line => {
      const toks = line.match(/[\p{L}\p{N}]+(?:[-'][\p{L}\p{N}]+)*|[^\p{L}\p{N}\s]+|\s+/gu) || [];
      const words = toks.map((x, k) => [k, x]).filter(([, x]) => /[\p{L}\p{N}]/u.test(x));
      const res = [...toks];
      for (let k = 0; k < words.length;) {
        let hit = null, n;
        for (n = 4; n >= 1 && !hit; n--) {
          if (k + n > words.length) continue;
          const seg = words.slice(k, k + n).map(w => norm(w[1]));
          hit = idx.get(seg.join(" ")) || idx.get([...seg.slice(0, -1), this.stem(seg[seg.length - 1], src)].join(" "));
          if (hit) {
            res[words[k][0]] = hit[j];
            for (let z = words[k][0] + 1; z <= words[k + n - 1][0]; z++) res[z] = "";
            k += n;
          }
        }
        if (!hit) k++;
      }
      return res.join("").replace(/\s{2,}/g, " ").trim();
    }).join("\n");
  },
  async web(text, src, dst) {
    const r = await fetch("https://api.mymemory.translated.net/get?" + new URLSearchParams({ q: text.slice(0, 480), langpair: `${src}|${dst}` }));
    const j = await r.json();
    const out = ((j.responseData || {}).translatedText || "").trim();
    if (!out || /MYMEMORY WARNING/i.test(out)) throw new Error(out || "web");
    return out;
  },
  /** → [çeviri, yol] · yol: ai | web | offline */
  async translate(text, dst) {
    text = String(text || "").trim();
    const src = this.detect(text);
    if (!text || src === dst) return [text, "offline"];
    if (navigator.onLine !== false) {
      if (Zeka.cfg()) { try { return [await Zeka.translate(text, src, dst), "ai"]; } catch (e) { /* sözlüğe düş */ } }
      try { return [await this.web(text, src, dst), "web"]; } catch (e) { /* sözlüğe düş */ }
    }
    return [this.offline(text, src, dst), "offline"];
  },
};
function translateButton(target) {
  return el("button.btn.tbtn", { type: "button", text: "🌐", title: t("Çevir (Türkçe · İngilizce · Arapça) — internet yoksa çevrim dışı sözlükle"),
    onclick: () => {
      if (!target.value.trim()) { toast(t("Önce çevrilecek metni yazın.")); return; }
      menu(t("Çevir"), [["tr", "Türkçe"], ["en", "English"], ["ar", "العربية"]].map(([c, n]) => [t("→ {x}", { x: n }), async () => {
        toast(t("Düşünüyor…"));
        const [out, how] = await Ceviri.translate(target.value, c);
        const box = el("textarea.in", { dir: c === "ar" ? "rtl" : "ltr" });
        box.value = out;
        const note = { ai: t("✦ Yapay zeka ile çevrildi"), web: t("🌐 Çevrim içi çeviri servisiyle çevrildi"),
          offline: t("📖 Çevrim dışı sözlükle kelime kelime çevrildi (yaklaşık) — internet olunca daha iyi çeviri alınır") }[how];
        sheet(t("Çeviri"), close => el("div", null, [el("div.hint", { text: note }), box, el("div.hrow", { style: { marginTop: "10px" } }, [
          el("button.btn.primary.grow", { text: t("Yerine yaz"), onclick: () => { target.value = box.value.trim(); close(); } }),
          el("button.btn.grow", { text: t("Altına ekle"), onclick: () => {
            target.value = (target.value.trim() ? target.value.trim() + (target.tagName === "TEXTAREA" ? "\n" : " / ") : "") + box.value.trim(); close(); } }),
          el("button.btn", { text: t("Kopyala"), onclick: () => { if (Native && Native.copy) Native.copy(box.value); else navigator.clipboard.writeText(box.value); toast(t("Kopyala") + " ✓"); } }),
        ])]));
      }]));
    } });
}

// ====================================================================== yapay zeka
const Zeka = {
  PROVIDERS: [["gemini", "Google Gemini", "gemini-flash-latest", "gemini-flash-latest", "https://aistudio.google.com/apikey"],
    ["openai", "OpenAI", "gpt-4o-mini", "gpt-4o-mini", "https://platform.openai.com/api-keys"],
    ["anthropic", "Anthropic Claude", "claude-haiku-5-5", "claude-haiku-5-5", "https://console.anthropic.com/settings/keys"],
    ["groq", "Groq", "llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct", "https://console.groq.com/keys"]],
  LANGS: { tr: "Türkçe", en: "English", ar: "العربية" },
  raw() { try { return FC.storage.get("ai", null) || {}; } catch (e) { return {}; } },
  cfg() { const a = this.raw(); return a.key && this.PROVIDERS.some(p => p[0] === a.provider) ? a : null; },
  info(pid) { return this.PROVIDERS.find(p => p[0] === pid) || this.PROVIDERS[0]; },
  async call(prompt, imageB64, mime, maxTokens) {
    const a = this.cfg();
    if (!a) throw Object.assign(new Error("nokey"), { kind: "nokey" });
    const info = this.info(a.provider), model = a.model || (imageB64 ? info[3] : info[2]);
    mime = mime || "image/jpeg";
    maxTokens = maxTokens || 900;
    let url, body, headers = { "Content-Type": "application/json" }, pick;
    if (a.provider === "gemini") {
      url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(a.key)}`;
      const parts = [{ text: prompt }];
      if (imageB64) parts.push({ inline_data: { mime_type: mime, data: imageB64 } });
      body = { contents: [{ parts }], generationConfig: { maxOutputTokens: maxTokens } };
      pick = j => j.candidates[0].content.parts.map(p => p.text || "").join("");
    } else if (a.provider === "anthropic") {
      url = "https://api.anthropic.com/v1/messages";
      Object.assign(headers, { "x-api-key": a.key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" });
      const content = [{ type: "text", text: prompt }];
      if (imageB64) content.unshift({ type: "image", source: { type: "base64", media_type: mime, data: imageB64 } });
      body = { model, max_tokens: maxTokens, messages: [{ role: "user", content }] };
      pick = j => j.content.filter(c => c.type === "text").map(c => c.text).join("");
    } else {
      url = a.provider === "groq" ? "https://api.groq.com/openai/v1/chat/completions" : "https://api.openai.com/v1/chat/completions";
      headers.Authorization = "Bearer " + a.key;
      const content = imageB64 ? [{ type: "text", text: prompt }, { type: "image_url", image_url: { url: `data:${mime};base64,${imageB64}` } }] : prompt;
      body = { model, max_tokens: maxTokens, messages: [{ role: "user", content }] };
      pick = j => j.choices[0].message.content;
    }
    try { if (FC.usage) FC.usage.count("ai." + a.provider); } catch (e) { /* sayaç isteğe bağlı */ }
    let r;
    try { r = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) }); } catch (e) { throw Object.assign(new Error("net"), { kind: "net" }); }
    const txt = await r.text();
    if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status} ${txt.slice(0, 200)}`),
      { kind: r.status === 429 ? "limit" : [400, 401, 403].includes(r.status) && /key|auth|permission/i.test(txt) ? "auth" : "other", detail: txt.slice(0, 200) });
    try { return String(pick(JSON.parse(txt)) || "").trim(); } catch (e) { throw Object.assign(new Error(txt.slice(0, 200)), { kind: "other" }); }
  },
  errorText(e) {
    return { nokey: t("Yapay zeka anahtarı girilmemiş (Ayarlar → Yapay zeka)."), net: t("İnternete bağlanılamadı; çevrim dışı cevap verildi."),
      auth: t("Yapay zeka anahtarı geçersiz. Ayarlar → Yapay zeka bölümünden kontrol edin."),
      limit: t("Yapay zeka sağlayıcınızın günlük / dakikalık sınırı doldu. Biraz sonra yeniden deneyin.") }[e && e.kind]
      || t("Yapay zeka cevap veremedi: {m}", { m: String(e && (e.detail || e.message) || e).slice(0, 160) });
  },
  context(items) {
    return items.slice(0, 500).map(d => [d.name, "x" + d.quantity, d.location_path ? "@" + d.location_path : "", d.category_path ? "#" + d.category_path : "",
      d.price != null ? `${d.price} ${d.currency}` : "", d.loan_to ? "loaned:" + d.loan_to : "", d.warranty_until ? "warranty:" + d.warranty_until : "",
      d.expires_on ? "expires:" + d.expires_on : "", d.shop_name ? "shop:" + d.shop_name : "", d.notes ? "note:" + d.notes.replace(/\n/g, " ").slice(0, 70) : ""]
      .filter(Boolean).join(" | ")).join("\n");
  },
  askOnline(q, items) {
    return this.call("You are the assistant inside a home inventory app called Organizer. Below is the user's item list (one item per line: " +
      "name | xQuantity | @Location path | #Category | price | loan/warranty/expiry/shop/notes). Today is " + todayStr() + ". Answer the user's " +
      "question ONLY from this list, briefly and concretely (at most 8 short lines), in " + this.LANGS[I18N.lang] + ". Always say WHERE an item is " +
      "(its location path). If nothing matches, say so and suggest the closest items.\n\nITEMS:\n" + this.context(items) + "\n\nQUESTION: " + q, null, null, 700);
  },
  TOPICS: { warranty: ["garanti", "warranty", "guarantee", "ضمان", "الضمان", "كفالة"],
    expiry: ["son kullanma", "skt", "bozul", "expire", "expiry", "best before", "انتهاء", "صلاحية", "الصلاحية"],
    loan: ["ödünç", "odunc", "emanet", "kimde", "loan", "lent", "borrow", "who has", "إعارة", "اعارة", "معار", "استعار"],
    low: ["az kal", "bitti", "bitmek", "tükendi", "almam lazım", "alışveriş", "low", "run out", "running out", "shopping", "نفد", "ناقص", "قليل", "التسوق"] },
  askOffline(q, items) {
    const nq = norm(q), days = warnDays();
    for (const [topic, words] of Object.entries(this.TOPICS)) {
      if (!words.some(w => nq.includes(norm(w)))) continue;
      if (topic === "warranty" || topic === "expiry") {
        const f = topic === "warranty" ? "warranty_until" : "expires_on";
        const rows = items.filter(d => d[f]).map(d => [d, daysLeft(d[f])]).filter(([, n]) => n !== null && n <= days).sort((a, b) => a[1] - b[1]);
        if (!rows.length) return [topic === "warranty" ? t("Önümüzdeki {n} gün içinde garantisi biten eşya yok.", { n: days })
          : t("Önümüzdeki {n} gün içinde son kullanma tarihi dolan eşya yok.", { n: days })];
        return rows.slice(0, 10).map(([d, n]) => `• ${d.name} — ${fmtDay(d[f])} (${n < 0 ? t("{n} gün önce bitti", { n: -n }) : n === 0 ? t("bugün bitiyor") : t("{n} gün kaldı", { n })}) · 📍 ${d.location_path || "—"}`);
      }
      if (topic === "loan") {
        const rows = items.filter(d => d.loan_to);
        return rows.length ? rows.slice(0, 10).map(d => `• ${d.name} → ${d.loan_to}` + (overdueDays(d) > 0 ? t(" · ⚠ {n} gün gecikti", { n: overdueDays(d) }) : ""))
          : [t("Ödünç verilmiş eşya yok.")];
      }
      const rows = items.filter(d => isLow(d) || d.to_buy || d.quantity === 0);
      return rows.length ? rows.slice(0, 12).map(d => `• ${d.name} — ${t("Adet:")} ${d.quantity}` + (d.min_qty ? ` / ${t("En az: {n}", { n: d.min_qty })}` : ""))
        : [t("Azalan ya da biten eşya yok.")];
    }
    const cmd = parseVoice(q);
    const COUNT = ["kaç", "kac", "how many", "how much", "كم"].map(norm);
    const terms = norm(cmd.query || q).split(/\s+/).filter(w => w.length > 1 && !COUNT.includes(w) && !QUESTION_WORDS.has(w));
    if (!terms.length) return [t("Sorunuzu biraz daha açık yazın: „Matkap nerede?“ · „Garantisi biten ne var?“")];
    let found = items.filter(d => { const hay = norm([d.name, d.notes, d.category_path, d.location_path].join(" ")); return terms.every(x => termIn(x, hay)); });
    if (!found.length) found = items.filter(d => terms.some(x => termIn(x, norm(d.name))));
    if (!found.length) return [t("„{x}“ bulunamadı.", { x: cmd.query || q })];
    const out = [];
    if (COUNT.some(w => nq.includes(w))) out.push(t("{n} kayıt · toplam {q} adet", { n: found.length, q: found.reduce((a, d) => a + d.quantity, 0) }));
    for (const d of found.slice(0, 8)) out.push(`• ${d.name} (×${d.quantity}) → 📍 ${d.location_path || t("yeri belirtilmemiş")}${d.loan_to ? t(" · ödünç: {x}", { x: d.loan_to }) : ""}`);
    if (found.length > 8) out.push(t("… ve {n} eşya daha", { n: found.length - 8 }));
    return out;
  },
  async suggest(blob) {
    const small = await shrinkPhoto(blob, 1024, 400000);
    const b64 = await blobToBase64(small || blob);
    const cats = Store.treeOrdered("categories").map(n => n.path);
    const locs = Store.treeOrdered("locations").map(n => n.path);
    const L = this.LANGS[I18N.lang];
    const txt = await this.call("Identify the single main household item / tool / object in this photo for a home inventory app. Reply ONLY with JSON: " +
      `{"name": short item name in ${L} (brand/model/size if visible), "category": the best matching category from CATEGORIES (exact text) or "", ` +
      `"location": a likely place from PLACES (exact text) or "", "notes": one short line in ${L} with visible details (brand, size, colour, model)}.\n` +
      "CATEGORIES: " + JSON.stringify(cats) + "\nPLACES: " + JSON.stringify(locs), b64, "image/jpeg", 300);
    const m = /\{[\s\S]*\}/.exec(txt);
    try { return JSON.parse(m ? m[0] : txt); } catch (e) { return {}; }
  },
  translate(text, src, dst) {
    return this.call(`Translate the following home-inventory text from ${this.LANGS[src]} to ${this.LANGS[dst]}. Keep numbers, sizes, brand and model ` +
      "names unchanged. Reply with the translation only.\n\n" + text, null, null, 500);
  },
};

function askPage(initial) {
  const q = el("input.in", { value: initial || "", placeholder: t("Örn. Kışlık montlar nerede? · Garantisi biten ne var? · Kaç ampulüm kaldı?") });
  const out = el("div.answer");
  const mode = el("div.hint");
  const draw = () => {
    const c = Zeka.cfg();
    mode.textContent = c ? t("Çevrim içi: {p} (kendi anahtarınızla). İnternet yoksa cihazdaki kayıtlardan cevaplanır.", { p: Zeka.info(c.provider)[1] })
      : t("Çevrim dışı cevap (cihazdaki kayıtlardan). Daha akıllı cevaplar için Ayarlar → Yapay zeka bölümüne kendi ücretsiz anahtarınızı girin.");
  };
  const go = async () => {
    const text = q.value.trim();
    if (!text) return;
    const items = Store.listItems({ sort: "name_asc" });
    const off = Zeka.askOffline(text, items);
    out.innerHTML = "";
    out.append(el("b", { text }));
    if (!Zeka.cfg()) { out.append(...off.map(x => el("div", { text: x }))); return; }
    const wait = el("div.hint", { text: t("Düşünüyor…") });
    out.append(wait);
    try {
      const ans = await Zeka.askOnline(text, items);
      wait.remove();
      out.append(el("div", { text: ans, style: { whiteSpace: "pre-line" } }), el("div.hint", { text: "✦ " + t("Çevrim içi yapay zeka") }));
    } catch (e) {
      wait.remove();
      out.append(...off.map(x => el("div", { text: x })), el("div.hint.lowtxt", { text: Zeka.errorText(e) }));
    }
  };
  q.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  fullPage({ title: t("✦  Asistan"), build: () => el("div", null, [
    el("div.hint", { text: t("Eşyalarınız hakkında soru sorun") }), mode,
    el("div.hrow", null, [q, el("button.btn.primary", { text: t("Sor"), onclick: go }),
      typeof Voice !== "undefined" && Voice.available() ? el("button.btn", { text: "🎤", onclick: async () => {
        try { toast(t("🎤 Dinliyorum… „Matkap nerede?“ ya da „3 ampul ekle“")); const v = await Voice.listen(); if (v) { q.value = v; go(); } }
        catch (e) { toast(t("Ses anlaşılamadı. Yeniden deneyin.")); }
      } }) : null]),
    el("div.chips", null, [t("Garantisi biten ne var?"), t("Kimde ödünç eşyam var?"), t("Neler azaldı?"), t("Son kullanma tarihi yaklaşanlar")]
      .map(s => el("button.chip", { text: s, onclick: () => { q.value = s; go(); } }))),
    out]) });
  draw();
  if (initial) go();
}

function aiCard() {
  const raw = Zeka.raw();
  const prov = el("select.in", null, Zeka.PROVIDERS.map(p => el("option", { value: p[0], text: p[1] })));
  prov.value = raw.provider || "gemini";
  const key = el("input.in.ltr", { type: "password", value: raw.key || "", placeholder: t("API anahtarı"), autocomplete: "off" });
  const model = el("input.in.ltr", { value: raw.model || "" });
  const ph = () => { model.placeholder = t("boş = varsayılan ({m})", { m: Zeka.info(prov.value)[2] }); };
  prov.onchange = ph;
  ph();
  const status = el("div.hint", { text: Zeka.cfg() ? t("Durum: anahtar girilmiş ✓") : t("Durum: anahtar yok — çevrim dışı çalışır") });
  const save = () => {
    FC.storage.set("ai", key.value.trim() ? { provider: prov.value, key: key.value.trim(), model: model.value.trim() } : { provider: prov.value, key: "" });
    status.textContent = Zeka.cfg() ? t("Durum: anahtar girilmiş ✓") : t("Durum: anahtar yok — çevrim dışı çalışır");
  };
  return el("div.card.section", null, [
    el("h3", { text: "✦  " + t("Yapay zeka (çevrim içi + çevrim dışı)") }),
    el("div.hint", { text: t("Asistan, fotoğraftan doldurma ve daha iyi çeviri için KENDİ ücretsiz anahtarınızı girin; programı dağıtan kişinin limitleri kullanılmaz. Anahtar yalnızca bu cihazda saklanır. İnternet ya da anahtar yoksa Asistan cihazdaki kayıtlardan, çeviri çevrim dışı sözlükten çalışır.") }),
    el("label.f", { text: t("Sağlayıcı:") }), prov,
    el("div.hint", { text: t("Google Gemini'nin ücretsiz kotası çoğu kullanım için yeterlidir.") }),
    el("label.f", { text: t("Anahtar:") }), el("div.hrow", null, [key, el("button.btn", { text: t("Anahtar al ↗"), onclick: () => openUrl(Zeka.info(prov.value)[4]) })]),
    el("label.f", { text: t("Model (isteğe bağlı):") }), model,
    el("div.hrow", { style: { marginTop: "10px" } }, [
      el("button.btn.primary.grow", { text: t("Kaydet"), onclick: save }),
      el("button.btn.grow", { text: t("Dene"), onclick: async () => {
        save();
        if (!Zeka.cfg()) return;
        status.textContent = t("Deneniyor…");
        try { status.textContent = t("✓ Çalışıyor: {x}", { x: (await Zeka.call("Reply with just the word: OK", null, null, 10)).slice(0, 80) }); }
        catch (e) { status.textContent = "⚠ " + Zeka.errorText(e); }
      } }),
    ]),
    status,
    el("div.hint", { text: t("Günlük yapay zeka çağrıları „Kullanım Limitleri“ kartında görünür.") }),
  ]);
}

// ====================================================================== dışa aktarma (Excel / CSV) ve sigorta envanteri
const CRC_TABLE = (() => { const tb = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; tb[n] = c >>> 0; } return tb; })();
function crc32(b) { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC_TABLE[(c ^ b[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
/** Sıkıştırmasız (stored) küçük zip: [[ad, metin|Uint8Array]] → Uint8Array */
function zipStore(files) {
  const enc = new TextEncoder(), parts = [], central = [];
  let off = 0;
  for (const [name, data] of files) {
    const nb = enc.encode(name), db = typeof data === "string" ? enc.encode(data) : data, crc = crc32(db);
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true); h.setUint32(14, crc, true);
    h.setUint32(18, db.length, true); h.setUint32(22, db.length, true); h.setUint16(26, nb.length, true);
    parts.push(new Uint8Array(h.buffer), nb, db);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true); c.setUint32(16, crc, true);
    c.setUint32(20, db.length, true); c.setUint32(24, db.length, true); c.setUint16(28, nb.length, true); c.setUint32(42, off, true);
    central.push(new Uint8Array(c.buffer), nb);
    off += 30 + nb.length + db.length;
  }
  const csize = central.reduce((a, x) => a + x.length, 0);
  const e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, csize, true); e.setUint32(16, off, true);
  const all = [...parts, ...central, new Uint8Array(e.buffer)], out = new Uint8Array(all.reduce((a, x) => a + x.length, 0));
  let p = 0;
  for (const x of all) { out.set(x, p); p += x.length; }
  return out;
}
const EXPORT_COLS = [["name", "Adı", 34], ["quantity", "Adet", 8], ["category_path", "Kategori", 26], ["location_path", "Yer", 26], ["price", "Fiyat", 12],
  ["currency", "Para birimi", 11], ["created_at", "Ekleme tarihi", 18], ["shop_name", "Dükkan/Kişi Adı", 24], ["shop_place", "Dükkan/Kişi Yeri", 24],
  ["shop_phone", "İletişim numarası", 18], ["warranty_until", "Garanti bitişi", 14], ["expires_on", "Son kullanma tarihi", 14], ["min_qty", "En az adet", 10],
  ["loan_to", "Ödünç", 18], ["loan_due", "Dönüş günü", 12], ["photo_count", "Fotoğraf", 9], ["receipt_count", "Fatura / fiş", 10], ["notes", "Notlar", 50]];
function exportTable(items) {
  const head = EXPORT_COLS.map(c => t(c[1]).replace(/:$/, ""));
  const rows = items.map(d => {
    const np = (d.photos || []).filter(p => !isReceipt(p)).length;
    const v = { ...d, photo_count: np, receipt_count: (d.photos || []).length - np };
    return EXPORT_COLS.map(([k]) => (["quantity", "price", "min_qty", "photo_count", "receipt_count"].includes(k) ? (v[k] == null ? null : Number(v[k])) : String(v[k] == null ? "" : v[k])));
  });
  return [head, rows];
}
function xmlEsc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])).replace(/\n/g, "&#10;"); }
function colName(n) { let s = ""; n++; while (n) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); } return s; }
function xlsxBytes(head, rows, title) {
  const cell = (ref, v, st) => v == null || v === "" ? `<c r="${ref}"${st ? ` s="${st}"` : ""}/>`
    : typeof v === "number" ? `<c r="${ref}"${st ? ` s="${st}"` : (Number.isInteger(v) ? "" : ' s="3"')}><v>${v}</v></c>`
      : `<c r="${ref}" t="inlineStr"${st ? ` s="${st}"` : ""}><is><t xml:space="preserve">${xmlEsc(v)}</t></is></c>`;
  const data = [`<row r="1">${cell("A1", title, 2)}</row>`, `<row r="2">${head.map((h, i) => cell(colName(i) + "2", h, 1)).join("")}</row>`,
    ...rows.map((r, n) => `<row r="${n + 3}">${r.map((v, i) => cell(colName(i) + (n + 3), v)).join("")}</row>`)];
  const last = colName(head.length - 1) + (rows.length + 2);
  const sheet = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<sheetViews><sheetView workbookViewId="0"${I18N.rtl ? ' rightToLeft="1"' : ""}><pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>` +
    `<cols>${EXPORT_COLS.map((c, i) => `<col min="${i + 1}" max="${i + 1}" width="${c[2]}" customWidth="1"/>`).join("")}</cols>` +
    `<sheetData>${data.join("")}</sheetData><autoFilter ref="A2:${last}"/></worksheet>`;
  const styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>' +
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font></fonts>' +
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1D5F74"/></patternFill></fill></fills>' +
    '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="4"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/>' +
    '<xf fontId="2" applyFont="1"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  const name = xmlEsc(t("Eşyalarım").slice(0, 31));
  return zipStore([
    ["[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'],
    ["_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'],
    ["xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      `xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${name}" sheetId="1" r:id="rId1"/></sheets>` +
      `<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'${name}'!$A$2:$${colName(head.length - 1)}$${rows.length + 2}</definedName></definedNames></workbook>`],
    ["xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'],
    ["xl/styles.xml", styles], ["xl/worksheets/sheet1.xml", sheet]]);
}
function bytesToB64(u8) { let s = ""; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); }
function shareBytes(name, mime, u8) {
  if (Native && Native.shareFile) Native.shareFile(name, mime, bytesToB64(u8));
  else { const a = el("a", { href: URL.createObjectURL(new Blob([u8], { type: mime })), download: name }); document.body.append(a); a.click(); a.remove(); }
}
function exportItems(kind) {
  const items = ItemsPage.items();
  if (!items.length) { toast(t("Listede eşya yok.")); return; }
  const [head, rows] = exportTable(items);
  const day = todayStr();
  if (kind === "xlsx") shareBytes(`Organizer-${day}.xlsx`, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    xlsxBytes(head, rows, t("Organizer — {n} eşya", { n: rows.length })));
  else {
    const q = v => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const csv = "﻿" + [head, ...rows].map(r => r.map(q).join(",")).join("\r\n");
    shareBytes(`Organizer-${day}.csv`, "text/csv", new TextEncoder().encode(csv));
  }
}
function exportMenu() {
  menu(t("Dışa aktar"), [[t("📊  Excel dosyası (.xlsx)…"), () => exportItems("xlsx")], [t("📄  CSV dosyası (.csv)…"), () => exportItems("csv")],
    [t("🛡  Sigorta envanteri (fotoğraflı PDF / yazdır)…"), () => insurancePage(ItemsPage.items())],
    [t("🖨  Döküm (kategori / yer)…"), () => reportPage(ItemsPage.cat !== null || ItemsPage.loc === null ? "categories" : "locations",
      ItemsPage.cat !== null || ItemsPage.loc === null ? ItemsPage.cat : ItemsPage.loc)]]);
}
function insurancePage(items) {
  const title = t("Ev eşyası envanteri (sigorta için)");
  fullPage({ title, build: () => {
    const totals = Store.totals(items), order = ["USD", ...CURRENCIES.map(c => c[0]).filter(c => c !== "USD")];
    const value = order.filter(c => c in totals).map(c => fmtPrice(totals[c], c)).join(" + ") || "—";
    const rep = el("div.report.insurance", null, [el("h1", { text: title, style: { textAlign: "center" } }),
      el("div.rsum", { style: { textAlign: "center" }, text: ["Organizer", fmtDate(nowStr()), t("{n} eşya · toplam {q} adet", { n: fmtNum(items.length), q: fmtNum(items.reduce((a, d) => a + d.quantity, 0)) }),
        t("Toplam değer") + ": " + value].join(" · ") })]);
    for (const d of items) {
      const pics = (d.photos || []).filter(p => !isReceipt(p)).slice(0, 2), recs = (d.photos || []).filter(isReceipt).length;
      const ph = el("div.insphotos");
      for (const p of pics) { const img = el("img", { alt: "" }); PhotoCache.url(p).then(u => { if (u) img.src = u; }); ph.append(img); }
      const facts = [[t("Adet"), String(d.quantity)], [t("Yer"), d.location_path || "—"], [t("Kategori"), d.category_path || "—"],
        [t("Alış fiyatı:").replace(/:$/, ""), fmtPrice(d.price, d.currency)], [t("Ekleme tarihi:").replace(/:$/, ""), fmtDate(d.created_at)]];
      const shop = [d.shop_name, d.shop_place, d.shop_phone].filter(Boolean).join(" · ");
      if (shop) facts.push([t("Satın alındığı yer"), shop]);
      if (d.warranty_until) facts.push([t("Garanti bitişi"), fmtDay(d.warranty_until)]);
      if (recs) facts.push([t("Fatura / fiş"), t("🧾 {n} belge", { n: recs })]);
      if (d.notes) facts.push([t("Notlar"), d.notes]);
      rep.append(el("div.insitem", null, [el("h2", { text: d.name }), pics.length ? ph : null,
        el("div.facts", null, facts.map(([k, v]) => el("div", null, [el("span", { text: k }), el("span", { text: v })])))]));
    }
    if (!items.length) rep.append(el("div.empty", { text: t("Bu bölümde kayıtlı eşya yok.") }));
    return el("div", null, [el("div.noprint", null, [el("div.hint", { text: t("Listede görünen eşyalar (arama ve filtreler geçerli). Fotoğraflar, alış fiyatı ve tarihi, garanti ve fatura bilgisiyle.") }),
      el("button.btn.primary.block", { text: t("🖨  Yazdır / PDF olarak kaydet"), onclick: () => printReport(title) })]), rep]);
  } });
  Layers.stack[Layers.stack.length - 1].layer.classList.add("report-layer");
}

// ====================================================================== yedek: şifreleme, otomatik yedek, geri yükleme
const OZB = new TextEncoder().encode("OZB1");
async function ozbKey(pw, salt, usage) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 200000, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, [usage]);
}
async function ozbEncrypt(bytes, pw) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await ozbKey(pw, salt, "encrypt"), bytes));
  const out = new Uint8Array(32 + ct.length);
  out.set(OZB); out.set(salt, 4); out.set(iv, 20); out.set(ct, 32);
  return out;
}
const isOzb = u8 => u8.length > 32 && OZB.every((b, i) => u8[i] === b);
async function ozbDecrypt(u8, pw) {
  try { return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: u8.slice(20, 32) }, await ozbKey(pw || "", u8.slice(4, 20), "decrypt"), u8.slice(32))); }
  catch (e) { throw Object.assign(new Error("wrong"), { kind: "wrong" }); }
}
function b64ToBytes(b64) { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; }

const AutoBackup = {
  PREFIX: "Organizer-otomatik-",
  available() { return !!(Native && Native.saveBackup); },
  settings() {
    return { freq: Store.get("auto_backup_freq", "weekly"), keep: parseInt(Store.get("auto_backup_keep", "10"), 10) || 10,
      pw: (() => { try { return decodeURIComponent(escape(atob(Store.get("auto_backup_pw", "") || ""))); } catch (e) { return ""; } })(),
      last: Store.get("auto_backup_last", "") };
  },
  async setPw(pw) { await Store.set("auto_backup_pw", pw ? btoa(unescape(encodeURIComponent(pw))) : ""); },
  due() {
    const s = this.settings(), days = { off: 0, daily: 1, weekly: 7 }[s.freq] ?? 7;
    if (!days || !this.available()) return false;
    return !s.last || Date.now() - new Date(s.last).getTime() >= days * 86400000 - 30 * 60000;
  },
  busy: false,
  async run(force) {
    if (this.busy || (!force && !this.due()) || !this.available()) return null;
    this.busy = true;
    try {
      const s = this.settings();
      let bytes = new TextEncoder().encode(await Store.exportAll());
      if (s.pw) bytes = await ozbEncrypt(bytes, s.pw);
      const d = new Date();
      const name = `${this.PREFIX}${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}.${s.pw ? "ozb" : "json"}`;
      const res = Native.saveBackup(name, bytesToB64(bytes), s.keep);
      if (res !== "ok") throw new Error(res);
      await Store.set("auto_backup_last", new Date().toISOString());
      return name;
    } finally { this.busy = false; }
  },
  list() { try { return JSON.parse(Native.listBackups() || "[]").sort((a, b) => b.name.localeCompare(a.name)); } catch (e) { return []; } },
};

/** Yedekten geri yükleme: hiçbir kayıt silinmez — o anki farklı hal Arşiv'e, yedekteki hal yeni değişiklik olarak yazılır. */
async function restoreBackup(bytes) {
  if (isOzb(bytes)) {
    let pw = await ask(t("Bu yedek şifreli. Şifreyi yazın:"), { input: true, yes: t("Geri yükle") });
    for (;;) {
      if (!pw) return;
      try { bytes = await ozbDecrypt(bytes, pw); break; } catch (e) { pw = await ask(t("Şifre yanlış. Yeniden yazın:"), { input: true, yes: t("Geri yükle") }); }
    }
  }
  let data;
  try { data = JSON.parse(new TextDecoder().decode(bytes)); } catch (e) { data = null; }
  if (!data || data.app !== "Organizer" || !data.tables) { await ask(t("Bu dosya bir Organizer yedeği değil ya da bozuk. ({m})", { m: "json" }), { no: false }); return; }
  if (!(await ask(t("Yedekteki kayıtlar geri getirilsin mi?\n\n• Hiçbir kayıt silinmez: şu anki farklı haller Arşiv'e alınır, yedekte olmayan kayıtlar yerinde kalır.\n• Başlamadan önce şu anki halin yedeği alınır.\n• Bulut bağlıysa geri gelen kayıtlar öbür cihazlara da gider."),
    { yes: t("Geri yükle") }))) return;
  toast(t("Yedek alınıyor…"));
  if (AutoBackup.available()) { try { await AutoBackup.run(true); } catch (e) { /* güvenlik yedeği alınamazsa da devam */ } }
  for (const [name, b64] of Object.entries(data.photos || {})) {
    if (!(await Store.hasPhoto(name))) await Store._put("photos", [{ name, blob: base64ToBlob(b64) }]);
  }
  const counts = {};
  for (const table of SYNC_TABLES) {
    const out = [], archive = [];
    for (const rec0 of data.tables[table] || []) {
      if (!rec0 || rec0.deleted) continue;
      const rec = { ...rec0 };
      const cur = Store.t[table].get(rec.uid);
      if (cur && !cur.deleted) {
        if (sameRecord({ ...cur, changelog: 0 }, { ...rec, changelog: 0 }) && !(table === "items" && cur.trashed_at)) continue;
        archive.push([table, { ...cur }, "yedek_oncesi", "yerel"]);
        if (table === "items" || table === "contacts") rec.photos = [...(rec.photos || []), ...(cur.photos || []).filter(p => !(rec.photos || []).includes(p))];
      }
      if (table === "items") {
        rec.trashed_at = "";
        rec.changelog = mergeChangelog(cur ? cur.changelog : [], rec.changelog);
        rec.changelog = mergeChangelog(rec.changelog, [{ t: nowUtc(), d: deviceName(), c: [], a: cur ? "yedekten" : "eklendi" }]);
      }
      const later = cur && cur.mtime >= nowUtc() ? new Date(new Date(cur.mtime).getTime() + 1).toISOString() : nowUtc();
      Object.assign(rec, { mtime: later, deleted: false });
      out.push(rec);
    }
    if (archive.length) await Store._archive(archive);
    if (out.length) {
      // eski hal zaten arşivde: applyRemote ikinci bir "çakışma" kaydı açmasın
      for (const r of out) { const cur = Store.t[table].get(r.uid); if (cur) cur.dirty = false; }
      await Store.applyRemote(table, out, true);
      counts[table] = out.length;
    }
  }
  Cloud.soon();
  App.render();
  const names = { items: t("Eşya"), contacts: t("Usta / dükkan"), locations: t("Yer"), categories: t("Kategori") };
  const sum = Object.entries(counts).map(([k, v]) => `${names[k]}: ${v}`).join(", ") || t("Yedekteki kayıtlar zaten bu cihazdakiyle aynı.");
  await ask(t("Geri yüklendi.") + "\n" + sum, { no: false });
}
function pickBackupFile() {
  const inp = el("input", { type: "file", accept: ".json,.ozb,application/json,application/octet-stream", style: { display: "none" } });
  inp.onchange = async () => {
    const f = inp.files && inp.files[0];
    inp.remove();
    if (f) await restoreBackup(new Uint8Array(await f.arrayBuffer()));
  };
  document.body.append(inp);
  inp.click();
}
function backupsPage() {
  fullPage({ title: t("Bu telefondaki otomatik yedekler"), build: () => {
    const box = el("div");
    const draw = () => {
      box.innerHTML = "";
      box.append(el("div.hint", { text: t("Otomatik yedekler telefonun Android/data/com.organizer.app/files/Yedekler klasörüne yazılır; „Paylaş“ ile Google Drive'a gönderebilirsiniz.") }));
      const list = AutoBackup.list();
      if (!list.length) box.append(el("div.empty", { text: t("henüz yok") }));
      for (const b of list) box.append(el("div.card.histrow", null, [el("b", { text: b.name }),
        el("div.hint", { text: `${fmtTs(new Date(b.time).toISOString())} · ${(b.size / 1048576).toFixed(1)} MB` }),
        el("div.hrow", null, [
          el("button.btn.grow", { text: t("Paylaş"), onclick: () => Native.shareFile(b.name, "application/octet-stream", Native.readBackup(b.name)) }),
          el("button.btn.primary.grow", { text: t("Geri yükle"), onclick: async () => { const b64 = Native.readBackup(b.name); if (b64) await restoreBackup(b64ToBytes(b64)); } }),
        ])]));
    };
    draw();
    return box;
  } });
}
function backupCard() {
  const s = AutoBackup.settings();
  const freq = el("select.in", null, [["off", t("Kapalı")], ["daily", t("Her gün")], ["weekly", t("Her hafta")]].map(([v, l]) => el("option", { value: v, text: l })));
  freq.value = s.freq;
  freq.onchange = () => Store.set("auto_backup_freq", freq.value);
  const keep = el("input.in", { type: "number", min: 1, max: 100, value: s.keep, style: { width: "110px" } });
  keep.onchange = () => Store.set("auto_backup_keep", String(Math.max(1, Math.min(100, parseInt(keep.value, 10) || 10))));
  const pw = el("input.in", { type: "password", value: s.pw, placeholder: t("boş = şifresiz"), autocomplete: "new-password" });
  pw.onchange = () => AutoBackup.setPw(pw.value);
  const status = el("div.hint");
  const draw = () => {
    const st = AutoBackup.settings();
    status.textContent = t("Son otomatik yedek: {x}", { x: st.last ? fmtTs(st.last) : t("henüz yok") }) +
      (AutoBackup.available() ? " · " + t("{n} yedek dosyası", { n: AutoBackup.list().length }) : "") + (st.freq === "off" ? " · " + t("otomatik yedek kapalı") : "");
  };
  draw();
  return el("div.card.section", null, [
    el("h3", { text: "💾  " + t("Otomatik yedek") }),
    !AutoBackup.available() ? el("div.hint", { text: t("Bu özellik için uygulamanın yeni sürümü gerekir.") }) : null,
    el("label.f", { text: t("Sıklık:") }), freq,
    el("label.f", { text: t("Saklanacak yedek sayısı:") }), keep, el("div.hint", { text: t("Daha eskileri kendiliğinden silinir.") }),
    el("label.f", { text: t("Yedek şifresi (isteğe bağlı):") }), pw,
    el("div.hint", { text: t("Şifreli yedek (.ozb) AES-256 ile korunur; şifreyi unutursanız yedek açılamaz.") }),
    el("button.btn.primary.block", { text: t("💾  Şimdi otomatik yedek al"), disabled: !AutoBackup.available(), onclick: async () => {
      await AutoBackup.setPw(pw.value);
      toast(t("Yedek alınıyor…"));
      try { const n = await AutoBackup.run(true); toast(t("Yedek alındı") + ": " + n); } catch (e) { toast(t("Yedek alınamadı: {m}", { m: e.message || e })); }
      draw();
    } }),
    el("button.btn.block", { text: t("Yedekleri göster"), disabled: !AutoBackup.available(), onclick: backupsPage }),
    el("button.btn.block", { text: t("♻  Yedekten geri yükle…"), onclick: pickBackupFile }),
    status,
  ]);
}

function prefsCard() {
  const warn = el("input.in", { type: "number", min: 1, max: 365, value: warnDays(), style: { width: "110px" } });
  warn.onchange = () => Store.set("warn_days", String(Math.max(1, Math.min(365, parseInt(warn.value, 10) || WARN_DAYS))));
  const dev = el("input.in", { value: Store.get("device_name", ""), placeholder: t("Telefon") });
  dev.onchange = () => Store.set("device_name", dev.value.trim());
  const start = el("select.in", null, [["panel", t("Ana sayfa")], ["items", t("Eşyalarım")]].map(([v, l]) => el("option", { value: v, text: l })));
  start.value = Store.get("start_page", "panel");
  start.onchange = () => Store.set("start_page", start.value);
  return el("div.card.section", null, [
    el("h3", { text: "⏳  " + t("Garanti / son kullanma hatırlatması:").replace(/:$/, "") }),
    warn, el("div.hint", { text: t("Bitişine bu kadar gün kala Ana sayfada ve açılışta hatırlatılır.") }),
    el("label.f", { text: t("Bu cihazın adı:") }), dev, el("div.hint", { text: t("Değişiklik geçmişinde „kim, hangi cihazdan“ olarak görünür.") }),
    el("label.f", { text: t("Açılışta gösterilecek sayfa:") }), start,
  ]);
}

// ====================================================================== açılış: hatırlatma + otomatik yedek
function startupExtras() {
  setTimeout(() => {
    const today = todayStr();
    if (Store.get("reminder_day", "") !== today) {
      const rem = reminders(Store.liveItems().map(d => ({ ...d })));
      Store.set("reminder_day", today);
      if (rem.length) toast(t("⏳ {n} eşyanın garantisi / son kullanma tarihi yaklaştı ya da geçti: {x}",
        { n: rem.length, x: rem.slice(0, 3).map(r => r[0].name).join(", ") + (rem.length > 3 ? " …" : "") }));
    }
  }, 2500);
  const tick = () => AutoBackup.run().catch(e => toast(t("Otomatik yedek alınamadı: {m}", { m: e.message || e })));
  setTimeout(tick, 60000);
  setInterval(tick, 30 * 60000);
}

App.pages[3] = PanelPage;   // app.js'deki App.pages = [Eşyalar, Ustalar, Ayarlar] + Ana sayfa (sekmede en başta gösterilir)
