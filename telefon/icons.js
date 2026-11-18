/* Meslek simgeleri (masaüstündeki duzenli_evim/professions.py ile aynı mantık).
 * 1) Bilinen meslekler programla gelen simgelerle eşleşir (img/meslek_simgeleri.json).
 * 2) Yeni bir meslek için simge internetten kendiliğinden bulunur (MyMemory çevirisi + Iconify) ve telefonda saklanır.
 * 3) Bulunamazsa usta için baretli adam, dükkan için dükkan simgesi gösterilir. */
"use strict";

const ICON_COLOR = "#1d5f74";

const Icons = {
  data: null,
  rules: [],
  cache: new Map(),   // slug -> svg (internetten bulunanlar)
  tried: new Set(),
  listeners: [],
  iconApi: "https://api.iconify.design",
  translateApi: "https://api.mymemory.translated.net",

  async init() {
    try {
      this.data = await (await fetch("img/meslek_simgeleri.json")).json();
    } catch (e) {
      this.data = { rules: [], icons: {}, default_usta: "", default_dukkan: "" };
    }
    this.rules = this.data.rules.map(([parts, key]) => [parts.map(norm), key]);
    try {
      const ov = localStorage.getItem("icon_api"); if (ov) this.iconApi = ov;
      const tv = localStorage.getItem("translate_api"); if (tv) this.translateApi = tv;
    } catch (e) { /* yok */ }
  },

  slug(text) { return norm(text).trim().replace(/\s+/g, "-").replace(/[^\w؀-ۿ-]/g, "").slice(0, 60) || "x"; },

  bundledKey(text) {
    const hay = " " + norm(text || "") + " ";
    if (!hay.trim()) return null;
    for (const [parts, key] of this.rules) if (parts.some(p => p && hay.includes(p))) return key;
    return null;
  },

  bundledSvg(key) {
    const body = (this.data.icons[key] || "").replace(/currentColor/g, ICON_COLOR);
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">${body}</svg>`;
  },

  /** Simgenin SVG metni (hemen döner; gerekirse arka planda internetten arar) */
  svg(text, kind) {
    const key = this.bundledKey(text);
    if (key) return this.bundledSvg(key);
    if (text && text.trim()) {
      const s = this.slug(text);
      if (this.cache.has(s)) return this.cache.get(s);
      this.fetch(text);
    }
    return this.bundledSvg(kind === "dukkan" ? this.data.default_dukkan : this.data.default_usta);
  },

  url(text, kind) { return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(this.svg(text, kind)); },

  /** <span class="badge"><img></span> */
  badge(text, kind, size) {
    const img = el("img", { alt: "", src: this.url(text, kind) });
    const b = el("span.badge", { style: size ? { width: size + "px", height: size + "px" } : null }, img);
    b.dataset.prof = text || "";
    b.dataset.kind = kind || "usta";
    return b;
  },

  async fetch(text) {
    const s = this.slug(text);
    if (this.tried.has(s) || this.bundledKey(text)) return;
    this.tried.add(s);
    const stored = await Store.getIcon(s).catch(() => null);
    let svg = stored;
    if (!svg) {
      svg = await this.lookupOnline(text).catch(() => null);
      if (svg) await Store.putIcon(s, svg).catch(() => {});
    }
    if (svg) {
      this.cache.set(s, svg);
      for (const f of this.listeners) f(s);
      // ekranda bu mesleği gösteren simgeleri yenile
      for (const b of document.querySelectorAll(".badge")) {
        if (this.slug(b.dataset.prof) === s) b.firstChild.src = this.url(b.dataset.prof, b.dataset.kind);
      }
    }
  },

  async _json(url) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 20000);
    try { const r = await fetch(url, { signal: ctl.signal }); return r.ok ? await r.json() : null; } finally { clearTimeout(timer); }
  },

  async translate(text) {
    const lang = /[؀-ۿ]/.test(text) ? "ar" : "tr";
    const d = await this._json(`${this.translateApi}/get?q=${encodeURIComponent(text)}&langpair=${lang}|en`).catch(() => null);
    let out = ((d && d.responseData && d.responseData.translatedText) || "").replace(/[^A-Za-z\s-]/g, " ").trim().toLowerCase();
    return out && out !== text.toLowerCase() ? out : "";
  },

  async lookupOnline(text) {
    const queries = [];
    if (/^[A-Za-z\s-]+$/.test(text.trim())) queries.push(text.trim().toLowerCase());
    const en = await this.translate(text);
    if (en) { const w = en.split(/\s+/); queries.push(en, w[w.length - 1], w[0]); }
    const seen = new Set();
    for (const q of queries) {
      if (!q || q.length < 3 || seen.has(q)) continue;
      seen.add(q);
      const key = this.bundledKey(q);
      if (key) return this.bundledSvg(key);
      const d = await this._json(`${this.iconApi}/search?query=${encodeURIComponent(q)}&limit=32&prefixes=mdi,tabler,material-symbols,ph,fluent,healthicons,game-icons`);
      const full = d && (d.icons || []).find(x => x.includes(":"));
      if (full) {
        const [prefix, name] = full.split(":");
        const r = await fetch(`${this.iconApi}/${prefix}/${name}.svg?color=${encodeURIComponent(ICON_COLOR)}&height=48`);
        const svg = r.ok ? await r.text() : "";
        if (svg.includes("<svg")) return svg;
      }
    }
    return null;
  },

  /** Açılışta: kayıtlı meslekler için önbellekteki simgeleri yükle */
  async warm() {
    for (const p of Store.professions()) {
      if (this.bundledKey(p)) continue;
      const svg = await Store.getIcon(this.slug(p)).catch(() => null);
      if (svg) this.cache.set(this.slug(p), svg);
    }
  },
};
