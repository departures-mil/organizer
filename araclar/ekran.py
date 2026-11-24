"""Masaüstü ekran görüntüleri (offscreen Qt; internete çıkmaz).
    QT_QPA_PLATFORM=offscreen python3 araclar/ekran.py <klasör> [tr-falcon-dark ar-falcon-light tr-klasik ...]
Her ad: <dil>-<şema>-<mod>[-<sayfa>] (mod yoksa dark; klasik için light). Sayfa: items | contacts | settings.
Geçici bir veri klasöründe örnek kayıtlarla açılır; gerçek kullanıcı verisine dokunmaz."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = r'''
import os, sys, json
sys.path.insert(0, os.path.join(sys.argv[1], "masaustu"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import organizer.app as A
out, page = sys.argv[2], sys.argv[3]
from fccore import updater as U
U.default_open = lambda url, timeout=30: (_ for _ in ()).throw(U.UpdateError("HTTP_404"))
from fccore import announcements as AN
AN.Announcements.refresh = lambda self: None
def go(ctl):
    w = ctl.win
    w.showNormal(); w.resize(1440, 900)
    w.show_page({"items": 0, "contacts": 1, "settings": 2}[page])
    if page == "items":
        it = w.items_page
        try:
            it.table.selectRow(0)
        except Exception:
            pass
    def snap():
        w.grab().save(out); print("kaydedildi", out); QApplication.instance().quit()
    QTimer.singleShot(1800, snap)
orig = A.Controller.build_window
def bw(self):
    orig(self)
    QTimer.singleShot(400, lambda: go(self))
A.Controller.build_window = bw
A.run()
'''


def sample(db_dir):
    sys.path.insert(0, os.path.join(ROOT, "masaustu"))
    from organizer.db import Database
    db = Database(db_dir)
    if db.count_items():
        return
    locs = {n: nid for nid, n, *_ in db.tree_ordered("locations")}
    cats = {n: nid for nid, n, *_ in db.tree_ordered("categories")}
    loc = next(iter(locs.values()), None)
    cat = next(iter(cats.values()), None)
    for name, qty, price in (("Akülü matkap", 1, 2450.0), ("Su terazisi", 2, 380.0), ("Uzatma kablosu 10 m", 3, 210.0),
                             ("Kombi filtresi", 4, 95.5), ("LED ampul E27", 12, 45.0), ("Silikon tabancası", 1, 160.0)):
        try:
            db.save_item({"name": name, "quantity": qty, "location_id": loc, "category_id": cat, "price": price,
                          "currency": "TRY", "notes": "", "created_at": "2026-11-20 10:00"})
        except Exception as e:  # noqa: BLE001
            print("örnek kayıt:", e)
            break


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ekranlar")
    names = sys.argv[2:] or ["tr-falcon-dark", "ar-falcon-light", "tr-klasik-light", "tr-falcon-dark-settings"]
    os.makedirs(out, exist_ok=True)
    for n in names:
        p = n.split("-")
        lang, scheme = p[0], p[1]
        mode = p[2] if len(p) > 2 and p[2] in ("dark", "light") else ("light" if scheme == "klasik" else "dark")
        page = p[-1] if p[-1] in ("items", "contacts", "settings") else "items"
        d = tempfile.mkdtemp(prefix="organizer-ekran-")
        sample(d)
        os.makedirs(os.path.join(d, "fccore"), exist_ok=True)
        with open(os.path.join(d, "fccore", "fccore.json"), "w", encoding="utf-8") as f:
            json.dump({"lang": lang, "scheme": scheme, "theme": mode, "onboarding.done": True, "whatsnew.seen": "9.9.9"}, f)
        env = dict(os.environ, ORGANIZER_DATA=d, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
        subprocess.run([sys.executable, "-c", CHILD,
                        ROOT, os.path.join(out, n + ".png"), page], env=env, check=False, timeout=120)


if __name__ == "__main__":
    main()
