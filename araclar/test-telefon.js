/* Telefon arayüzü duman testi (Playwright, tarayıcıda): açılış hatasız, çekirdek üst çubuğu, ayarlarda iletişim EN SON,
   eşitleme kuralı (uzak silme → arşiv, çakışma → yedek, geri alma), klasik şema kayıtlı, Arapça RTL.
     node araclar/test-telefon.js     (PLAYWRIGHT_CORE / PLAYWRIGHT_BROWSERS_PATH isteğe bağlı) */
'use strict';
const path = require('path'), http = require('http'), fs = require('fs'), assert = require('assert');
const pw = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const ROOT = path.join(__dirname, '..', 'telefon');
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json', '.woff2': 'font/woff2' };

(async () => {
  const srv = await new Promise(res => { const s = http.createServer((q, r) => {
    const u = decodeURIComponent(q.url.split('?')[0]); const f = path.join(ROOT, u === '/' ? 'index.html' : u);
    if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); return r.end(); }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
  }).listen(0, '127.0.0.1', () => res(s)); });
  const browser = await pw.chromium.launch();
  const p = await browser.newPage({ viewport: { width: 412, height: 860 } });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  await p.route(/github\.com|githubusercontent|firestore|googleapis|formsubmit/, r => r.fulfill({ status: 404, body: '' }));
  await p.addInitScript(() => { localStorage.setItem('fc.onboarding.done', 'true'); });
  await p.goto('http://127.0.0.1:' + srv.address().port + '/');
  await p.waitForFunction(() => typeof App !== 'undefined' && document.querySelector('#tbHost .topbar-actions'), null, { timeout: 20000 });
  const r = await p.evaluate(async () => {
    const out = {};
    out.version = APP_VERSION;
    out.top = [...document.querySelectorAll('#tbHost .topbar-actions > *')].map(e => e.className);
    out.klasik = FC.look.schemes().includes('klasik');
    // eşitleme kuralı
    const loc = Store.treeRows('locations')[0];
    const uid = await Store.saveItem({ name: 'Matkap', quantity: 1, location: loc.uid, category: '', price: 10, currency: 'TRY', notes: '' }, []);
    const cur = Store.t.items.get(uid);
    await Store.applyRemote('items', [{ ...cur, deleted: true, photos: [], mtime: '2099-01-01T00:00:00.000Z' }]);
    out.afterDelete = Store.liveItems().filter(i => i.uid === uid).length;
    out.arsiv = Store.archiveList().map(a => a.kind + ':' + a.name);
    await Store.archiveRestore(Store.archiveList()[0].id);
    out.restored = Store.liveItems().filter(i => i.uid === uid).length;
    out.restoredDirty = Store.t.items.get(uid).dirty;
    const c2 = Store.t.items.get(uid);   // dirty (gönderilmemiş) → uzak değişiklik üstüne yazınca yedek
    await Store.applyRemote('items', [{ ...c2, name: 'Uzak', mtime: '2099-02-01T00:00:00.000Z' }]);
    out.conflict = Store.archiveList()[0].kind + ':' + Store.archiveList()[0].name;
    out.newName = Store.t.items.get(uid).name;
    // ---- 2.3.0: değişiklik geçmişi, garanti, filtre, panel, dışa aktarma, şifreli yedek, çeviri, Asistan
    const u2 = await Store.saveItem({ name: 'Kışlık mont', quantity: 2, location: loc.uid, category: '', price: 40, currency: 'USD', notes: '',
      warranty_until: todayStr(), expires_on: '' }, []);
    await Store.changeQuantity(u2, 1);
    out.log = Store.t.items.get(u2).changelog.map(e => (e.a || '') + ':' + (e.c || []).map(c => c.join('>')).join(','));
    ItemsPage.adv = { flags: ['warranty_soon'] };
    out.filtered = ItemsPage.items().map(d => d.name);
    ItemsPage.adv = {};
    App.tab = 3; App.render();
    out.panel = document.querySelectorAll('.tiles .tile').length;
    const [head, rows] = exportTable(Store.listItems({}));
    const x = xlsxBytes(head, rows, 'T');
    out.xlsx = x[0] === 0x50 && x[1] === 0x4b && rows.length;
    const enc = await ozbEncrypt(new TextEncoder().encode('merhaba'), 'pw');
    out.ozb = isOzb(enc) && new TextDecoder().decode(await ozbDecrypt(enc, 'pw'));
    try { await ozbDecrypt(enc, 'yanlis'); out.wrong = false; } catch (e) { out.wrong = e.kind; }
    out.tr = Ceviri.offline('Şarjlı matkap ve uç seti', 'tr', 'en');
    out.ask = Zeka.askOffline('Kışlık montlar nerede?', Store.listItems({})).join(' | ');
    // geri yükleme: hiçbir şey silinmez
    const backup = JSON.parse(await Store.exportAll());
    await Store.changeQuantity(u2, 5);
    const u3 = await Store.saveItem({ name: 'Sonra', quantity: 1, location: '', category: '', price: null, currency: 'USD', notes: '' }, []);
    window.ask = async () => true;
    await restoreBackup(new TextEncoder().encode(JSON.stringify(backup)));
    out.restoreQty = Store.t.items.get(u2).quantity;
    out.restoreKeeps = !!Store.t.items.get(u3) && !Store.t.items.get(u3).deleted;
    out.restoreLog = Store.t.items.get(u2).changelog.slice(-1)[0].a;
    App.tab = 2; App.render();
    const cards = [...document.querySelectorAll('.org-settings > *')];
    out.lastCard = cards[cards.length - 1].getAttribute('data-card') || cards[cards.length - 1].className + '|' + cards[cards.length - 1].textContent.slice(0, 40);
    out.firstCard = cards[0].textContent.slice(0, 30);
    FC.i18n.set('ar');
    await new Promise(r => setTimeout(r, 300));
    out.dir = document.documentElement.dir; out.lang = I18N.lang;
    return out;
  });
  console.log(JSON.stringify(r, null, 1));
  const want = fs.readFileSync(path.join(__dirname, '..', 'masaustu', 'organizer', '__init__.py'), 'utf8').match(/__version__ = "([^"]+)"/)[1];
  assert.strictEqual(r.version, want, 'telefon ve masaüstü aynı sürüm');
  assert.ok(r.top.some(c => /sync-act/.test(c)) && r.top.some(c => /lan-act/.test(c)) && r.top.some(c => /top-act-wrap/.test(c)), 'Eşitle · Wi-Fi · Güncelle');
  const iS = r.top.findIndex(c => /sync-act/.test(c)), iL = r.top.findIndex(c => /lan-act/.test(c)), iU = r.top.findIndex(c => /top-act-wrap/.test(c));
  assert.ok(iS < iL && iL < iU, 'sıra: Eşitle · Wi-Fi · Güncelle');
  assert.ok(r.klasik, 'klasik şema');
  assert.strictEqual(r.afterDelete, 0); assert.deepStrictEqual(r.arsiv, ['silindi:Matkap']);
  assert.strictEqual(r.restored, 1); assert.strictEqual(r.restoredDirty, true);
  assert.strictEqual(r.conflict, 'cakisma:Matkap'); assert.strictEqual(r.newName, 'Uzak');
  assert.ok(/Admin|contact|iletişim/i.test(r.lastCard), 'Admin ile iletişim EN SON: ' + r.lastCard);
  assert.ok(/Görünüm/.test(r.firstCard), 'Görünüm başta: ' + r.firstCard);
  assert.strictEqual(r.dir, 'rtl'); assert.strictEqual(r.lang, 'ar');
  assert.deepStrictEqual(r.log, ['eklendi:', ':quantity>2>3'], 'değişiklik geçmişi');
  assert.deepStrictEqual(r.filtered, ['Kışlık mont'], 'gelişmiş filtre');
  assert.strictEqual(r.panel, 5, 'Ana sayfa kutucukları');
  assert.ok(r.xlsx, 'xlsx');
  assert.strictEqual(r.ozb, 'merhaba'); assert.strictEqual(r.wrong, 'wrong');
  assert.strictEqual(r.tr, 'cordless drill and bit set');
  assert.ok(/Kışlık mont/.test(r.ask), 'Asistan: ' + r.ask);
  assert.strictEqual(r.restoreQty, 3); assert.ok(r.restoreKeeps, 'geri yükleme silmez'); assert.strictEqual(r.restoreLog, 'yedekten');
  assert.deepStrictEqual(errors, [], 'sayfa hataları');
  await browser.close(); srv.close();
  console.log('telefon testi: TAMAM');
})().catch(e => { console.error(e); process.exit(1); });
