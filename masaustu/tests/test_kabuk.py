"""Masaüstü kabuğu (offscreen Qt): fccore üst çubuk sırası, tam ekran açılış, ayarlar sırası, klasik şema, dil değişimi."""
import json
import os

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def ctl(tmp_path_factory):
    d = tmp_path_factory.mktemp("veri")
    os.environ["ORGANIZER_DATA"] = str(d)
    os.makedirs(d / "fccore")
    (d / "fccore" / "fccore.json").write_text(json.dumps({"onboarding.done": True, "lang": "tr"}))
    from fccore import updater as U
    U.default_open = lambda url, timeout=30: (_ for _ in ()).throw(U.UpdateError("HTTP_404"))
    from fccore import announcements as AN
    AN.Announcements.refresh = lambda self: None
    import organizer.app as A
    box = {}
    orig = A.Controller.build_window

    def bw(self):
        orig(self)
        box["ctl"] = self
        QTimer.singleShot(300, QApplication.instance().quit)
    A.Controller.build_window = bw
    A.run()
    return box["ctl"]


def test_tam_ekran_ve_ust_cubuk(ctl):
    w = ctl.win
    assert w.isFullScreen()
    tb = w.tb
    order = [tb.sync_btn, tb.lan_btn, tb.upd_btn, tb.theme_btn]
    xs = [b.mapTo(tb, b.rect().topLeft()).x() for b in order]
    assert xs == sorted(xs), "Eşitle · Wi-Fi · Güncelle · Tema sırası"
    wc = [tb.b_min, tb.b_half, tb.b_full, tb.b_close]
    xw = [b.mapTo(tb, b.rect().topLeft()).x() for b in wc]
    assert xw == sorted(xw) and xw[0] > xs[-1], "Küçült · Orta · Tam ekran · Kapat en sağda"


def test_orta_ve_tam_ekran(ctl):
    w = ctl.win
    w.toggle_half()
    assert w.half and not w.isFullScreen()
    w.toggle_half()
    assert w.isFullScreen()


def test_ayarlar_iletisim_en_son(ctl):
    sp = ctl.win.settings_page
    items = sp.grid.items
    keys = [c.property("fcCard") for c in items]
    for k in ("look", "usage", "crash", "about"):
        assert k in keys, k
    assert items[-1] is sp.grid.contact, "Admin ile iletişim EN SONDA"


def test_klasik_sema(ctl):
    from fccore import style
    assert "klasik" in style.schemes()
    style.set_scheme("klasik")
    assert style.tok("accent") == "#2a9d8f" or style.tok("accent") == "#7fd1c5"
    style.set_scheme("falcon")


def test_dil_degisimi_arapca(ctl):
    from fccore import i18n as fci
    from organizer import i18n
    fci.set("ar")
    assert i18n.LANG == "ar" and QApplication.instance().layoutDirection().name == "RightToLeft"
    assert ctl.win.items_page is not None
    fci.set("tr")
    assert i18n.LANG == "tr"
