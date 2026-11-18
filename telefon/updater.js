/* Uygulama içinden güncelleme (telefon). Masaüstündeki organizer/updater.py ile aynı düzen.
 * 1.4.0'dan itibaren önce GitHub'a bakılır (herkese açık depo, bulut hesabı gerekmez):
 *   https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme/organizer-telefon.json
 *   → {surum, notlar, kabuk, boyut, sha256, imza, dosya}; paket: .../guncelleme/<dosya>
 * GitHub'a ulaşılamazsa eski yol (Firebase) denenir:
 * Firebase'de: guncelleme/organizer-telefon → {surum, notlar, kabuk, boyut, parca, sha256, imza}
 *              guncelleme/organizer-telefon-<surum>-<i> → {veri: zip parçası}
 *              guncelleme/organizer-telefon-apk (+ parçaları) → Java kabuğu da değiştiyse imzalı APK
 * İmza Java tarafında (MainActivity) doğrulanır; imzası tutmayan paket kurulmaz. */
"use strict";

const GITHUB_RAW = "https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme";

const Updater = {
  state: "",        // "", checking, none, available, installing, ready, error
  manifest: null,
  message: "",
  listeners: [],
  done: 0, total: 0, speed: 0, _tl: 0, _dl: 0,   // indirme bilgisi (bayt, bayt/sn)

  emit() { for (const f of this.listeners) f(); },
  native() { return typeof Native !== "undefined" && Native && Native.installWeb ? Native : null; },
  kabuk() { const n = this.native(); return n && n.kabuk ? n.kabuk() : 1; },
  vkey(v) { return String(v || "0").split(".").map(x => parseInt(x, 10) || 0); },
  newer(a, b) {
    const x = this.vkey(a), y = this.vkey(b);
    for (let i = 0; i < Math.max(x.length, y.length); i++) { const p = x[i] || 0, q = y[i] || 0; if (p !== q) return p > q; }
    return false;
  },
  skipped() { const n = this.native(); return n && n.skipped ? n.skipped().split(/\s+/) : []; },
  needsApk() { return !!this.manifest && (parseInt(this.manifest.kabuk, 10) || 1) > this.kabuk(); },

  async client() {
    const c = new FirebaseClient(Cloud.config());
    await c.resume(Store.get("fb_refresh"));
    return c;
  },

  async ghJson(kind) {
    const r = await fetch(`${GITHUB_RAW}/${kind}.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error("GitHub " + r.status);
    const man = await r.json();
    man._kaynak = "github";
    return man;
  },

  async manifest(kind) {
    try {
      return await this.ghJson(kind);
    } catch (e) {
      if (!Cloud.isConnected()) throw new Error(t("Güncelleme sunucusuna ulaşılamadı. İnternet bağlantısını denetleyin."));
      const man = await (await this.client()).getDoc("guncelleme/" + kind);
      if (man) man._kaynak = "firebase";
      return man;
    }
  },

  async check() {
    if (this.state === "checking" || this.state === "installing" || this.state === "ready") return;
    this.state = "checking"; this.message = ""; this.emit();
    try {
      const man = await this.manifest("organizer-telefon");
      const ok = man && man.surum && this.newer(man.surum, APP_VERSION) && !this.skipped().includes(man.surum);
      this.manifest = ok ? man : null;
      this.state = ok ? "available" : "none";
    } catch (e) {
      this.state = "error";
      this.message = e instanceof SyncError ? syncErrorText(e) : String(e);
    }
    this.emit();
  },

  /** GitHub'dan parça parça indirir (yüzde, MB ve hız gösterilir). */
  async _ghDownload(man) {
    if (!/^[A-Za-z0-9._-]+$/.test(man.dosya || "")) throw new Error(t("Güncelleme paketi bozuk indi. Yeniden deneyin."));
    const r = await fetch(`${GITHUB_RAW}/${man.dosya}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok || !r.body) throw new Error(t("Güncelleme paketi eksik. Biraz sonra yeniden deneyin."));
    const total = parseInt(man.boyut, 10) || 0;
    this.total = total; this.done = 0; this.speed = 0; this._dl = 0;
    const t0 = this._tl = performance.now();
    this.message = "%0"; this.emit();
    const reader = r.body.getReader();
    const parts = [];
    let got = 0, lastEmit = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value); got += value.length;
      const now = performance.now();
      if (now - lastEmit > 200 || got >= total) {
        const inst = (got - this._dl) / Math.max(0.001, (now - this._tl) / 1000);
        this.speed = this.speed ? this.speed * 0.5 + inst * 0.5 : got / Math.max(0.001, (now - t0) / 1000);
        this._tl = now; this._dl = got; lastEmit = now;
        this.done = got; this.total = Math.max(total, got);
        this.message = "%" + this.percent(); this.emit();
      }
    }
    this.done = got; this.emit();
    return this._verify(man, parts);
  },

  async _download(c, kind, man) {
    if (man._kaynak === "github") return this._ghDownload(man);
    if (typeof c === "function") c = await c();
    const parts = [];
    const n = parseInt(man.parca, 10) || 0;
    this.total = parseInt(man.boyut, 10) || 0; this.done = 0; this.speed = 0; this._dl = 0;
    const t0 = this._tl = performance.now();
    this.message = "%0"; this.emit();
    for (let i = 0; i < n; i++) {
      const doc = await c.getDoc(`guncelleme/${kind}-${man.surum}-${i}`);
      if (!doc || !(doc.veri instanceof Bytes)) throw new Error(t("Güncelleme paketi eksik. Biraz sonra yeniden deneyin."));
      parts.push(b64ToBytes(doc.veri.b64));
      const now = performance.now(), done = this.done + parts[parts.length - 1].length;
      const inst = (done - this._dl) / Math.max(0.001, (now - this._tl) / 1000);
      this.speed = this.speed ? this.speed * 0.5 + inst * 0.5 : (done / Math.max(0.001, (now - t0) / 1000));
      this._tl = now; this._dl = done;
      this.done = done; this.total = Math.max(this.total, done);
      this.message = "%" + this.percent(); this.emit();
    }
    return this._verify(man, parts);
  },

  async _verify(man, parts) {
    const total = parts.reduce((a, p) => a + p.length, 0);
    const all = new Uint8Array(total);
    let off = 0;
    for (const p of parts) { all.set(p, off); off += p.length; }
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", all))].map(b => b.toString(16).padStart(2, "0")).join("");
    if (total !== (parseInt(man.boyut, 10) || -1) || hash !== man.sha256) throw new Error(t("Güncelleme paketi bozuk indi. Yeniden deneyin."));
    return bytesToB64(all);
  },

  async install() {
    if (this.state !== "available" || !this.manifest) return;
    const nat = this.native();
    this.state = "installing"; this.message = ""; this.emit();
    try {
      const c = () => this.client();
      if (this.needsApk()) {
        const apk = await this.manifest("organizer-telefon-apk");
        if (!apk || !apk.surum) throw new Error(t("Bu güncelleme için gereken paket bulunamadı."));
        const b64 = await this._download(c, "organizer-telefon-apk", apk);
        const err = nat && nat.installApk ? await nat.installApk(b64, apk.imza || "") : t("Bu cihazda kurulamaz.");
        if (err) throw new Error(err);
        this.state = "none"; this.manifest = null;   // Android'in kendi "Güncelle" onayı açıldı
      } else {
        const b64 = await this._download(c, "organizer-telefon", this.manifest);
        const err = nat ? await nat.installWeb(this.manifest.surum, b64, this.manifest.imza || "") : t("Bu cihazda kurulamaz.");
        if (err) throw new Error(err);
        this.state = "ready";
        this.emit();
        toast(t("{n} kuruldu. Uygulama yeniden başlatılıyor…", { n: this.manifest.surum }));
        setTimeout(() => this.restart(), 1500);
        return;
      }
    } catch (e) {
      this.state = "error";
      this.message = e instanceof SyncError ? syncErrorText(e) : (e && e.message) || String(e);
    }
    this.emit();
  },

  percent() { return this.total ? Math.min(100, Math.floor(this.done * 100 / this.total)) : 0; },
  eta() { return this.speed && this.total ? Math.max(0, Math.round((this.total - this.done) / this.speed)) : null; },
  num(x, d) { const s = x.toFixed(d); return I18N.lang === "tr" ? s.replace(".", ",") : s; },
  mb(b) { return this.num(b / 1048576, 1); },
  rows() {
    const sp = !this.speed ? "—" : this.speed >= 1048576 ? t("{x} MB/sn", { x: this.num(this.speed / 1048576, 1) })
      : t("{x} KB/sn", { x: this.num(this.speed / 1024, 0) });
    const e = this.eta();
    const eta = e == null ? t("hesaplanıyor…") : e < 60 ? t("yaklaşık {s} sn", { s: Math.max(1, e) })
      : t("yaklaşık {m} dk {s} sn", { m: Math.floor(e / 60), s: e % 60 });
    return [
      [t("İnen"), t("{a} / {b} MB", { a: this.mb(this.done), b: this.mb(this.total) })],
      [t("Kalan"), t("{a} MB", { a: this.mb(Math.max(this.total - this.done, 0)) })],
      [t("Hız"), sp],
      [t("Kalan süre"), eta],
    ];
  },
  /** İndirme sırasında: başlık + yüzde, ilerleme çubuğu, alt alta düzenli bilgi satırları */
  progressBox() {
    const box = el("div.dl-box");
    const head = el("div.dl-head", null, [el("b.dl-title"), el("b.dl-pct")]);
    const bar = el("div.dl-bar", null, el("i"));
    const grid = el("div.dl-grid");
    box.append(head, bar, grid);
    box.draw = () => {
      $(".dl-title", box).textContent = t("Güncelleme indiriliyor: {n}", { n: (this.manifest || {}).surum || "" });
      $(".dl-pct", box).textContent = "%" + this.percent();
      $(".dl-bar i", box).style.width = this.percent() + "%";
      grid.textContent = "";
      for (const [k, v] of this.rows()) grid.append(el("span.k", { text: k }), el("span.v", { text: v }));
    };
    return box;
  },

  restart() {
    const n = this.native();
    if (n && n.restart) n.restart(); else location.reload();
  },

  /** Ayarlar sayfasındaki kart */
  card() {
    const status = el("div.hint", { style: { whiteSpace: "pre-line" } });
    const prog = this.progressBox();
    const btn = el("button.btn.block");
    const draw = () => {
      const man = this.manifest || {};
      let text = t("Sürüm {v}", { v: APP_VERSION }), label = t("🔄  Güncellemeleri denetle"), primary = false, enabled = true;
      if (this.state === "checking") { text = t("Sürüm {v} · Güncellemeler denetleniyor…", { v: APP_VERSION }); enabled = false; }
      else if (this.state === "none") text = t("Sürüm {v} · Program güncel.", { v: APP_VERSION });
      else if (this.state === "available") {
        text = t("Sürüm {v} · Yeni sürüm hazır: {n}", { v: APP_VERSION, n: man.surum }) + (man.notlar ? "\n" + man.notlar : "");
        if (this.needsApk()) text += "\n" + t("Bu güncellemede Android bir kez \"Güncelle\" onayı isteyecek.");
        label = t("⬆  Şimdi güncelle ({n})", { n: man.surum }); primary = true;
      } else if (this.state === "installing") { text = t("Sürüm {v}", { v: APP_VERSION }); enabled = false; label = t("⬇  İndiriliyor %{p}", { p: this.percent() }); }
      else if (this.state === "ready") { text = t("{n} kuruldu. Uygulama yeniden başlatılıyor…", { n: man.surum }); label = t("↻  Yeniden başlat"); primary = true; }
      else if (this.state === "error") {
        text = t("Sürüm {v}", { v: APP_VERSION }) + "\n⚠ " + this.message;
      }
      status.textContent = text;
      prog.style.display = this.state === "installing" ? "" : "none";
      if (this.state === "installing") prog.draw();
      btn.textContent = label;
      btn.disabled = !enabled;
      btn.classList.toggle("primary", primary);
    };
    btn.onclick = () => {
      if (this.state === "available") this.install();
      else if (this.state === "ready") this.restart();
      else this.check();
    };
    this.cardDraw = draw;
    draw();
    return el("div.card.section", null, [el("h3", { text: t("⬆  Güncelleme") }), status, prog, el("div", { style: { marginTop: "10px" } }, btn)]);
  },

  /** Üst çubuktaki "Güncelle" düğmesi (sağ üst köşe) */
  drawBanner() { if (typeof TopBar !== "undefined") TopBar.drawUpdate(); },

  init() {
    this.listeners.push(() => { this.drawBanner(); if (this.cardDraw && App.tab === 2) this.cardDraw(); });
    // açılıştan kısa süre sonra bir kez yeni sürüm var mı diye bak (GitHub; bulut hesabı beklenmez)
    setTimeout(() => this.check(), 4000);
  },
};

function b64ToBytes(b64) {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

function bytesToB64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
