/* Telefon arayüzü ekran görüntüleri (Playwright, tarayıcıda; Android köprüsü yok → host "browser").
     PLAYWRIGHT_CORE=/opt/npm-tools/node_modules/playwright-core PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
       node araclar/ekran-telefon.js <klasör> [tr-falcon-dark ar-falcon-light tr-klasik-light tr-falcon-dark-ayarlar]
   Örnek kayıtlarla açılır (geçici tarayıcı profili); gerçek veriye dokunmaz. */
'use strict';
const path = require('path'), http = require('http'), fs = require('fs');
const pw = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const ROOT = path.join(__dirname, '..', 'telefon');
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json', '.woff2': 'font/woff2', '.svg': 'image/svg+xml' };

function serve() {
  return new Promise(res => {
    const s = http.createServer((q, r) => {
      const u = decodeURIComponent(q.url.split('?')[0]);
      const f = path.join(ROOT, u === '/' ? 'index.html' : u);
      if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); return r.end(); }
      r.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
      fs.createReadStream(f).pipe(r);
    }).listen(0, '127.0.0.1', () => res(s));
  });
}

(async () => {
  const out = path.resolve(process.argv[2] || 'ekranlar');
  const names = process.argv.slice(3).length ? process.argv.slice(3) : ['tr-falcon-dark', 'ar-falcon-light', 'tr-klasik-light', 'tr-falcon-dark-ayarlar'];
  fs.mkdirSync(out, { recursive: true });
  const srv = await serve();
  const base = 'http://127.0.0.1:' + srv.address().port + '/';
  const browser = await pw.chromium.launch();
  const errors = [];
  for (const n of names) {
    const [lang, scheme, mode0, page0] = n.split('-');
    const mode = mode0 === 'light' || mode0 === 'dark' ? mode0 : (scheme === 'klasik' ? 'light' : 'dark');
    const page = (mode0 === 'ayarlar' || page0 === 'ayarlar') ? 'ayarlar' : 'esyalar';
    const ctx = await browser.newContext({ viewport: { width: Number(process.env.EKRAN_GENISLIK || 412), height: (mode0 === 'ayarlar' || page0 === 'ayarlar') ? 4200 : 860 }, deviceScaleFactor: 2, locale: lang });
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(n + ': ' + e.message));
    await p.route(/github\.com|githubusercontent|firestore|googleapis|formsubmit/, r => r.fulfill({ status: 404, body: '' }));
    await p.addInitScript(([l, s, m]) => {
      const set = (k, v) => localStorage.setItem('fc.' + k, JSON.stringify(v));
      if (!localStorage.getItem('fc.lang')) { set('lang', l); set('scheme', s); set('theme', m); set('onboarding.done', true); set('whatsnew.seen', '9.9.9'); }
    }, [lang, scheme, mode]);
    await p.goto(base);
    await p.waitForFunction(() => typeof App !== 'undefined' && document.querySelector('#tbHost .topbar-actions'));
    await p.evaluate(async () => {
      if (Store.liveItems().length) return;
      const loc = Store.treeRows('locations')[0], cat = Store.treeRows('categories')[0];
      for (const [name, q, pr] of [['Akülü matkap', 1, 2450], ['Su terazisi', 2, 380], ['Uzatma kablosu 10 m', 3, 210], ['LED ampul E27', 12, 45]])
        await Store.saveItem({ name, quantity: q, location: loc ? loc.uid : '', category: cat ? cat.uid : '', price: pr, currency: 'TRY', notes: '' }, []);
      App.render();
    });
    if (page === 'ayarlar') await p.evaluate(() => { App.tab = 2; App.render(); });
    await p.waitForTimeout(700);
    await p.screenshot({ path: path.join(out, n + '.png'), fullPage: false });
    console.log('kaydedildi', path.join(out, n + '.png'));
    await ctx.close();
  }
  await browser.close();
  srv.close();
  if (errors.length) { console.error('SAYFA HATALARI:\n' + errors.join('\n')); process.exit(1); }
})().catch(e => { console.error(e); process.exit(1); });
