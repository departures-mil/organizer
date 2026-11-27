/* Organizer telefon — ortak çekirdek kabuğu (cekirdek/fc-core.js). app.js'ten ÖNCE yüklenir; App.start() içinden
   Kabuk.baslat() çağrılır (Store açıldıktan sonra).
   Burada: üst çubuk (Fiyatları gizle · Hızlı ara · Duyurular · Eşitle · Wi‑Fi · Güncelle · Tema · Dil | Kapat),
   "klasik" renk şeması (2.1'e kadarki petrol yeşili görünüm), dil ve tema köprüsü (FC ↔ I18N / Theme), Kullanım Limitleri
   (FC.usage.wrapFetch: Firestore REST istekleri kendiliğinden sayılır), ilk açılış rehberi (kendi Firebase'iniz → hesaba giriş),
   "neler yeni", duyurular, çökme raporu ve Android güncellemesi (Java tarafında GitHub indirmesi + ApkPatchInstaller). */
(function () {
  'use strict';
  var APP = 'organizer', REPO = 'organizer';
  var AB = window.AndroidBridge || null;

  FC.i18n.add({
    tr: {
      'org.eye': 'Fiyatları gizle / göster', 'org.scan': 'Hızlı ara',
      'org.arsiv': 'Arşiv ve çakışma yedekleri', 'org.arsiv.desc': 'Başka cihazda silinen kayıtlar bu telefonda silinmez, burada arşivlenir. Eşitlemede üstüne yazılan değişikliklerinizin eski hali de burada durur. İstediğinizi geri alabilirsiniz.',
      'org.arsiv.bos': 'Arşivde kayıt yok.', 'org.arsiv.geri': 'Geri al', 'org.arsiv.geriAlindi': 'Geri alındı: {s}', 'org.arsiv.fazla': '… ve {n} kayıt daha',
      'org.arsiv.silindi': 'başka cihazda silindi', 'org.arsiv.cakisma': 'çakışma yedeği', 'org.arsiv.temizlendi': 'çöp kutusundan temizlendi', 'org.arsiv.yedek_oncesi': 'yedekten geri yüklemeden önceki hali',
      'org.tablo.items': 'Eşya', 'org.tablo.contacts': 'Usta / dükkan', 'org.tablo.locations': 'Yer', 'org.tablo.categories': 'Kategori',
      'org.fb.doldur': 'Firebase bilgileri yazıldı. Şimdi e-posta ve şifrenizle hesaba bağlanın.'
    },
    en: {
      'org.eye': 'Hide / show prices', 'org.scan': 'Quick search',
      'org.arsiv': 'Archive and conflict backups', 'org.arsiv.desc': 'Records deleted on another device are not deleted on this phone; they are archived here. Older versions of your changes overwritten during sync are kept here too. You can restore any of them.',
      'org.arsiv.bos': 'The archive is empty.', 'org.arsiv.geri': 'Restore', 'org.arsiv.geriAlindi': 'Restored: {s}', 'org.arsiv.fazla': '… and {n} more',
      'org.arsiv.silindi': 'deleted on another device', 'org.arsiv.cakisma': 'conflict backup', 'org.arsiv.temizlendi': 'emptied from the trash', 'org.arsiv.yedek_oncesi': 'version before restoring from backup',
      'org.tablo.items': 'Item', 'org.tablo.contacts': 'Craftsman / shop', 'org.tablo.locations': 'Place', 'org.tablo.categories': 'Category',
      'org.fb.doldur': 'The Firebase details were filled in. Now sign in with your e-mail and password.'
    },
    ar: {
      'org.eye': 'إخفاء / إظهار الأسعار', 'org.scan': 'بحث سريع',
      'org.arsiv': 'الأرشيف والنسخ الاحتياطية للتعارضات', 'org.arsiv.desc': 'السجلات المحذوفة على جهاز آخر لا تُحذف على هذا الهاتف بل تُؤرشف هنا. وتبقى هنا أيضاً النسخ القديمة من تغييراتك التي استُبدلت أثناء المزامنة. يمكنك استعادة أيٍّ منها.',
      'org.arsiv.bos': 'الأرشيف فارغ.', 'org.arsiv.geri': 'استعادة', 'org.arsiv.geriAlindi': 'تمت الاستعادة: {s}', 'org.arsiv.fazla': '… و{n} سجلات أخرى',
      'org.arsiv.silindi': 'حُذف على جهاز آخر', 'org.arsiv.cakisma': 'نسخة احتياطية للتعارض', 'org.arsiv.temizlendi': 'أُفرغ من سلة المحذوفات', 'org.arsiv.yedek_oncesi': 'النسخة قبل الاستعادة من النسخة الاحتياطية',
      'org.tablo.items': 'غرض', 'org.tablo.contacts': 'حرفي / محل', 'org.tablo.locations': 'مكان', 'org.tablo.categories': 'تصنيف',
      'org.fb.doldur': 'تمت كتابة بيانات Firebase. سجّل الدخول الآن ببريدك الإلكتروني وكلمة المرور.'
    }
  });
  var T = function (k, v) { return FC.t(k, v); };

  /* ---------- "klasik" şema: 2.1'e kadarki app.css renkleri (açık = :root, koyu = [data-theme=dark]) ---------- */
  FC.look.registerScheme('klasik', {
    label: { tr: 'Klasik (eski görünüm)', en: 'Classic (previous look)', ar: 'الكلاسيكي (المظهر السابق)' },
    light: {
      '--bg': '#fbf6ee', '--bg-grid': '#0000', '--panel': '#ffffff', '--panel-solid': '#ffffff', '--panel-hover': '#f2efe8',
      '--border': '#c9dadd', '--border-strong': '#2a9d8f', '--border-w': '1px', '--text': '#20323a', '--muted': '#6b8590', '--label': '#1d5f74',
      '--nav-text': '#6b8590', '--nav-title': '#8aa3aa', '--accent': '#2a9d8f', '--accent-2': '#143f4d', '--on-accent': '#ffffff',
      '--primary-1': '#2a9d8f', '--primary-2': '#238a7e', '--active-1': '#f6bd6066', '--active-2': '#f6bd6040', '--active-line': '#f6bd60',
      '--accent-soft': '#e6f3f1', '--accent-line': '#2a9d8f59', '--focus': '#2a9d8f', '--focus-w': '2px', '--focus-ring': '#d6efec',
      '--danger': '#c0392b', '--warn': '#b7791f', '--ok': '#1f9d55', '--ok-text': '#1f7a45', '--danger-text': '#c0392b', '--warn-text': '#9a6416',
      '--ok-soft': '#e8f7ee', '--ok-line': '#1f9d5559', '--danger-soft': '#fdf0ee', '--danger-line': '#f3c7c1', '--warn-soft': '#fff6e5', '--warn-line': '#f6bd60',
      '--sidebar-bg': '#ffffff', '--topbar-bg': '#1d5f74', '--modal-bg': '#ffffff', '--modal-border': '#c9dadd', '--backdrop': '#0f1d2273',
      '--toast-bg': '#142830eb', '--toast-text': '#ffffff', '--toast-line': '#142830', '--toast-err-bg': '#c0392b', '--toast-err-text': '#ffffff', '--toast-err-line': '#c0392b',
      '--badge-text': '#1d5f74', '--badge-bg': '#e6f3f1', '--badge-line': '#c9dadd', '--on-badge': '#ffffff',
      '--bar-track': '#d5e3e6', '--scroll-thumb': '#1d5f7440', '--glow-1': '#d6efec', '--glow-2': '#fbe9d3',
      '--shadow-pop': '0 8px 24px #1d5f7426', '--shadow-modal': '0 20px 60px #1d5f7440', '--shadow-toast': '0 8px 24px #0000004d'
    },
    dark: {
      '--bg': '#111a1e', '--bg-grid': '#0000', '--panel': '#1b262c', '--panel-solid': '#18242a', '--panel-hover': '#22343a',
      '--border': '#36494f', '--border-strong': '#2a9d8f', '--border-w': '1px', '--text': '#e2ebee', '--muted': '#93a9b2', '--label': '#7fd1c5',
      '--nav-text': '#93a9b2', '--nav-title': '#6f878f', '--accent': '#2a9d8f', '--accent-2': '#0b2229', '--on-accent': '#ffffff',
      '--primary-1': '#2a9d8f', '--primary-2': '#238a7e', '--active-1': '#f6bd6040', '--active-2': '#f6bd6026', '--active-line': '#8a6a2e',
      '--accent-soft': '#1d3a3a', '--accent-line': '#7fd1c559', '--focus': '#7fd1c5', '--focus-w': '2px', '--focus-ring': '#1d3a3a',
      '--danger': '#f08b7e', '--warn': '#f6bd60', '--ok': '#6ee7a0', '--ok-text': '#6ee7a0', '--danger-text': '#f08b7e', '--warn-text': '#f0c98a',
      '--ok-soft': '#173525', '--ok-line': '#1f9d55', '--danger-soft': '#3a2220', '--danger-line': '#5a2f2a', '--warn-soft': '#33291a', '--warn-line': '#8a6a2e',
      '--sidebar-bg': '#172126', '--topbar-bg': '#12343f', '--modal-bg': '#1b262c', '--modal-border': '#36494f', '--backdrop': '#000000a6',
      '--toast-bg': '#142830eb', '--toast-text': '#ffffff', '--toast-line': '#2a9d8f', '--toast-err-bg': '#3a2220', '--toast-err-text': '#ffffff', '--toast-err-line': '#f08b7e',
      '--badge-text': '#7fd1c5', '--badge-bg': '#1d3a3a', '--badge-line': '#36494f', '--on-badge': '#0b2229',
      '--bar-track': '#2a3a40', '--scroll-thumb': '#7fd1c540', '--glow-1': '#12302f', '--glow-2': '#2a2117',
      '--shadow-pop': '0 8px 24px #00000080', '--shadow-modal': '0 20px 60px #000000a6', '--shadow-toast': '0 8px 24px #00000080'
    }
  });

  /* ---------- Android: güncelleme yerel tarafta (Java'da GitHub indirmesi + kurulu APK + yama → yeni APK; hata → tam APK) ---------- */
  if (FC.host.kind === 'android' && AB && typeof AB.apkUpdate === 'function') {
    FC.host.update.run = function (plan, onEv) {
      return new Promise(function (resolve, reject) {
        window.__fcApk = function (ev) {
          if (!ev) return;
          if (ev.type === 'progress') onEv({ patch: !!ev.patch, done: ev.done, total: ev.total, finished: !!ev.finished });
          else if (ev.type === 'patchFailed') onEv({ patchFailed: true, error: ev.error });
          else if (ev.type === 'installing') onEv({ installing: true });
          else if (ev.type === 'done') resolve(ev.result || 'done');
          else if (ev.type === 'error') reject(Object.assign(new Error(ev.error || 'FAILED'), { code: ev.error || 'FAILED' }));
        };
        try {
          AB.apkUpdate(JSON.stringify({ version: plan.version, full: plan.full, patch: plan.mode === 'patch' ? { url: plan.url, sha256: plan.sha256, size: plan.size } : null }));
        } catch (e) { reject(e); }
      });
    };
    FC.host.can.update = true;
  }
  /* Android: latest.json yerelde indirilir (WebView'den GitHub'a fetch CORS'a takılır → "Failed to fetch"); ortak-cekirdek 1c11eb0 ile aynı sözleşme */
  if (FC.host.kind === 'android' && AB && typeof AB.httpGet === 'function') {
    var httpSeq = 0, httpWait = {};
    window.__fcHttp = function (id, r) { var f = httpWait[id]; if (f) { delete httpWait[id]; f(r || {}); } };
    FC.host.net = {
      maxBytes: 2 * 1024 * 1024,
      download: function (url, onProgress) {
        return new Promise(function (resolve, reject) {
          var id = 'h' + (++httpSeq) + '_' + Date.now();
          var to = setTimeout(function () { delete httpWait[id]; reject(Object.assign(new Error('TIMEOUT'), { code: 'TIMEOUT' })); }, 45000);
          httpWait[id] = function (r) {
            clearTimeout(to);
            if (r.error) return reject(Object.assign(new Error(String(r.error)), { code: 'NETWORK' }));
            if (r.status !== 200) return reject(Object.assign(new Error('HTTP_' + r.status), { code: 'HTTP_' + r.status }));
            var b = new TextEncoder().encode(String(r.body || ''));
            if (onProgress) try { onProgress({ done: b.length, finished: true }); } catch (e) { /* yok */ }
            resolve(b);
          };
          try { AB.httpGet(id, url); } catch (e) { clearTimeout(to); delete httpWait[id]; reject(e); }
        });
      }
    };
  }

  /* ---------- Kullanım Limitleri: Firestore REST (fetch) istekleri kendiliğinden sayılır ---------- */
  FC.usage.wrapFetch();

  var tb = null, bekleyenFb = null, basladi = false;

  function eskiKullanici() {
    try {
      return !!(Store.get('sync_last', null) || Store.get('fb_refresh', null) || Store.liveItems().length || Store.get('labels_v1', null));
    } catch (e) { return false; }
  }

  function ob() {
    return {
      firebase: !Cloud.isConnected(), ai: false,
      onFirebase: function (cfg) { bekleyenFb = cfg; },
      onClose: function () {
        if (!bekleyenFb || Cloud.isConnected()) return;
        var cfg = bekleyenFb; bekleyenFb = null;
        Store.set('fb_config', JSON.stringify(cfg, null, 2)).then(function () {
          App.tab = 2; App.render();
          setTimeout(function () { accountForm(); FC.ui.toast(T('org.fb.doldur'), 'info', 7000); }, 150);
        });
      }
    };
  }

  function dugme(cls, onclick) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'icon-btn ' + cls;
    b.addEventListener('click', onclick);
    return b;
  }

  var Kabuk = {
    /** App.start() → Store açıldıktan sonra: dil/tema taşınır, çekirdek başlar, üst çubuk kurulur. */
    baslat: function () {
      if (basladi) return; basladi = true;
      // 2.1'den gelen kullanıcı: dil ve koyu/açık seçimi çekirdeğe taşınır; rehber yerine "neler yeni" gösterilir
      if (FC.storage.get('lang', null) == null) FC.i18n.set(Store.get('language', 'tr'));
      if (FC.storage.get('theme', null) == null) {
        var th = Store.get('theme', null);
        if (th === 'light' || th === 'dark' || th === 'auto') FC.storage.set('theme', th);
        else if (eskiKullanici()) FC.storage.set('theme', 'light');
      }
      if (eskiKullanici()) {
        if (FC.storage.get('onboarding.done', null) == null) FC.storage.set('onboarding.done', true);
        if (FC.storage.get('whatsnew.seen', null) == null) FC.storage.set('whatsnew.seen', '2.1.0');
      }
      FC.look.apply();
      FC.init({ app: APP, repo: REPO, version: APP_VERSION, channel: FC.host.kind === 'android' ? 'android' : undefined,
        announcements: true, onboarding: ob() });
      if (I18N.lang !== FC.i18n.lang()) { I18N.setLanguage(FC.i18n.lang()); Store.set('language', FC.i18n.lang()); }
      FC.i18n.onChange(function (l) { App.changeLanguage(l); });
      FC.look.onChange(function () { Theme.apply(); App.render(true); });
      Kabuk.ustCubuk();
    },

    ustCubuk: function () {
      var host = document.getElementById('tbHost');
      if (!host || tb) return;
      var eye = dugme('org-eye', async function () {
        PRICES_HIDDEN = !PRICES_HIDDEN;
        await Store.set('prices_hidden', PRICES_HIDDEN ? '1' : '0');
        App.render(true);
      });
      var scan = dugme('org-scan', function () {
        if (App.tab === 2) { App.tab = 0; App.render(); }
        window.scrollTo(0, 0);
        var inp = document.querySelector('#page .search input');
        if (inp) { inp.focus(); inp.select(); }
      });
      var before = [eye, scan];
      if (FC.announcements) before.push(FC.announcements.button());
      tb = FC.topbar.mount(host, {
        before: before,
        sync: { onClick: function () { App.syncClick(); } },
        lan: { onClick: function () { App.tab = 2; App.render(); setTimeout(function () { var c = document.getElementById('lanCard'); if (c) c.scrollIntoView({ block: 'center' }); }, 60); } }
      });
      Kabuk.ciz();
    },

    /** Üst çubuktaki uygulama düğmeleri (fiyat gizle, hızlı ara) dil/durum değişince */
    ciz: function () {
      var eye = document.querySelector('#tbHost .org-eye'), scan = document.querySelector('#tbHost .org-scan');
      if (eye) { eye.innerHTML = svgIcon(PRICES_HIDDEN ? 'eyeOff' : 'eye'); eye.classList.toggle('on', PRICES_HIDDEN); eye.title = T('org.eye'); eye.setAttribute('aria-label', T('org.eye')); }
      if (scan) { scan.innerHTML = svgIcon('scan'); scan.title = T('org.scan'); scan.setAttribute('aria-label', T('org.scan')); }
    },

    /** Eşitle düğmesinin durumu: idle | syncing | error | off */
    esitleme: function (metin) {
      if (!tb) return;
      var busy = Cloud.busy || Lan.busy;
      var on = Cloud.isConnected();
      var st = busy ? 'syncing' : !on ? (Lan.peer() && !Lan.lastError ? 'idle' : 'off') : Cloud.lastError ? 'error' : 'idle';
      var n = 0;
      try { var d = Store.dirtyRecords(); for (var k in d) n += d[k].length; } catch (e) { n = 0; }
      tb.setSync(st, st === 'off' ? 0 : n);
      tb.setLan(Lan.busy ? 'busy' : Lan.available() && Lan.peer() ? 'on' : 'off');
      var b = document.querySelector('#tbHost .sync-act');
      if (b && metin) b.title = metin;
    },

    /** Ayarlar sayfasının sonuna çekirdek kartları: Görünüm (başa) · uygulama kartları · Asistan Agent · Kullanım Limitleri ·
        Otomatik hata raporu · Hakkında · Admin ile iletişim (EN SON) */
    ayarlar: function (root, kartlar) {
      var grid = document.createElement('div');
      grid.className = 'settings-grid org-settings';
      root.appendChild(grid);
      FC.settings.build(grid, { cards: kartlar, usage: { firebase: true, ai: true, project: function () { try { return Cloud.isConnected() ? (Cloud.config() || {}).projectId : ''; } catch (e) { return ''; } } },
        about: { version: APP_VERSION }, onboarding: ob() });
      return grid;
    },

    arsivKarti: function () {
      var c = document.createElement('div');
      c.className = 'card'; c.id = 'arsivCard';
      function ciz() {
        c.innerHTML = '';
        c.appendChild(FC.ui.el('h3.card-title', { html: FC.ui.icon('box') + '<span>' + FC.ui.esc(T('org.arsiv')) + '</span>' }));
        c.appendChild(FC.ui.el('p.card-desc', { text: T('org.arsiv.desc') }));
        var list = Store.archiveList(30), total = Store.archiveCount();
        if (!list.length) { c.appendChild(FC.ui.el('p.muted', { text: T('org.arsiv.bos') })); return; }
        list.forEach(function (a) {
          var row = FC.ui.el('div.org-arsiv');
          row.appendChild(FC.ui.el('div', null, [FC.ui.el('b', { text: T('org.tablo.' + a.table) + ': ' + (a.name || '—') }),
            FC.ui.el('div.muted', { text: T('org.arsiv.' + a.kind) + ' · ' + fmtDate(String(a.at).replace('T', ' ').slice(0, 16)) })]));
          row.appendChild(FC.ui.el('button.btn.small', { type: 'button', text: T('org.arsiv.geri'), onclick: async function () {
            await Store.archiveRestore(a.id);
            FC.ui.toast(T('org.arsiv.geriAlindi', { s: a.name || '—' }), 'info');
            Cloud.soon(); ciz();
          } }));
          c.appendChild(row);
        });
        if (total > list.length) c.appendChild(FC.ui.el('p.muted', { text: T('org.arsiv.fazla', { n: total - list.length }) }));
      }
      ciz();
      return c;
    }
  };
  window.Kabuk = Kabuk;
})();
