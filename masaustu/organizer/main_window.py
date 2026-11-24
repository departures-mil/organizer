"""Ana pencere (2.2.0'dan beri ortak çekirdek fccore kabuğu).

FcWindow (çerçevesiz, her açılışta tam ekran) + Shell (kenar çubuğu, üst çubuk, sayfalar). Sağ üst sıra:
[Fiyatları gizle · Hızlı ara · Duyurular] · Eşitle · Wi-Fi · Güncelle · Tema · Dil | Küçült · Orta · Tam ekran · Kapat.
Sayfaların içeriği uygulamanın kendi widget'larıdır; dil değişince içerikler yeniden kurulur (pencere ve üst çubuk kalır).
"""
from PySide6.QtCore import QDateTime, QLocale, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from fccore import i18n as fci
from fccore import icons as fcicons
from fccore._icons import PATHS
from fccore.widgets import button
from fccore.window import FcWindow, Shell

from . import __version__, common, i18n
from .i18n import t
from .paths import asset

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# uygulamaya özgü simgeler (fccore simge kümesine eklenir; çizgi stili aynı)
PATHS.setdefault("wrench", '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>')
PATHS.setdefault("eye", '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>')
PATHS.setdefault("eyeOff", '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1"/>'
                           '<path d="M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>')
PATHS.setdefault("scan", '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
                         '<path d="M7 12h10"/>')
PATHS.setdefault("archive", '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/>'
                            '<path d="M10 12h4"/>')

# fccore sözlüğüne kabuk metinleri (kenar çubuğu, sayfa başlıkları, üst çubuk düğmeleri)
fci.add({
    "tr": {"org.name": "Organizer", "org.tag": "Evdeki her şey yerli yerinde", "org.nav": "Ev",
           "org.items": "Eşyalarım", "org.items.sub": "Eşyalar, yerler, kategoriler, fotoğraflar ve fiyatlar",
           "org.contacts": "Ustalar ve Dükkanlar", "org.contacts.sub": "Usta, dükkan ve telefon numaraları",
           "org.sys": "Sistem", "org.settings": "Ayarlar",
           "org.settings.sub": "Yerler, kategoriler, bulut, yerel ağ, görünüm, güncelleme ve iletişim",
           "org.eye": "Fiyatları gizle / göster", "org.scan": "Hızlı ara / barkod okuyucu (Ctrl+F)"},
    "en": {"org.name": "Organizer", "org.tag": "Everything at home in its place", "org.nav": "Home",
           "org.items": "My items", "org.items.sub": "Items, places, categories, photos and prices",
           "org.contacts": "Craftsmen & Shops", "org.contacts.sub": "Craftsmen, shops and phone numbers",
           "org.sys": "System", "org.settings": "Settings",
           "org.settings.sub": "Places, categories, cloud, local network, appearance, updates and contact",
           "org.eye": "Hide / show prices", "org.scan": "Quick search / barcode reader (Ctrl+F)"},
    "ar": {"org.name": "المنظِّم", "org.tag": "كل شيء في البيت في مكانه", "org.nav": "البيت",
           "org.items": "أغراضي", "org.items.sub": "الأغراض والأماكن والتصنيفات والصور والأسعار",
           "org.contacts": "الحرفيون والمحلات", "org.contacts.sub": "الحرفيون والمحلات وأرقام الهواتف",
           "org.sys": "النظام", "org.settings": "الإعدادات",
           "org.settings.sub": "الأماكن والتصنيفات والسحابة والشبكة المحلية والمظهر والتحديث والتواصل",
           "org.eye": "إخفاء / إظهار الأسعار", "org.scan": "بحث سريع / قارئ الباركود (Ctrl+F)"},
})


class PageHost(QWidget):
    """Shell sayfası: içeriği dil değişince yeniden kurulabilen kap."""

    def __init__(self, factory, margins=(28, 22, 28, 22)):
        super().__init__()
        self.factory = factory
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(0)
        self.page = None
        self.build()

    def build(self):
        old = self.page
        self.page = self.factory()
        # sayfanın kendi büyük başlığı üst çubukta zaten yazıyor
        for lbl in self.page.findChildren(QLabel, "PageTitle"):
            lbl.hide()
        self.lay.addWidget(self.page)
        if old is not None:
            old.hide()
            self.lay.removeWidget(old)
            old.deleteLater()
        return self.page


class MainWindow(FcWindow):
    """Organizer ana penceresi. ctl: app.Controller (db, sync, lan, core)."""

    def __init__(self, ctl):
        super().__init__(t("Organizer"))
        self.ctl = ctl
        self.db, self.sync, self.lan, self.core = ctl.db, ctl.sync, ctl.lan, ctl.core
        self.setMinimumSize(900, 600)
        sh = self.shell = Shell(self, name="Organizer", tag="org.tag", version=__version__, logo="box")
        sh.brand_name.setText(fci.t("org.name"))
        sh.vbadge.setText("v" + __version__)
        pm = QPixmap(asset("logo.png"))
        if not pm.isNull():
            sh.logo.setProperty("fcIcon", None)
            sh.logo.setStyleSheet("background: transparent;")
            sh.logo.setPixmap(pm.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        from .contacts_page import ContactsPage
        from .items_page import ItemsPage
        from .settings_page import SettingsPage
        self.items_host = PageHost(lambda: ItemsPage(self.db))
        self.contacts_host = PageHost(lambda: ContactsPage(self.db))
        self.settings_host = PageHost(self._settings_page, margins=(28, 22, 28, 28))
        sh.nav_group("org.nav")
        sh.page("items", "org.items", "box", self.items_host, sub="org.items.sub", scroll=False)
        sh.page("contacts", "org.contacts", "wrench", self.contacts_host, sub="org.contacts.sub", scroll=False)
        sh.nav_group("org.sys")
        sh.page("settings", "org.settings", "settings", self.settings_host, sub="org.settings.sub", scroll=False)
        sh.page_changed.connect(self._page_changed)
        self.keys = ["items", "contacts", "settings"]

        # saat (kenar çubuğunun altında)
        self.clock = QLabel(alignment=Qt.AlignCenter)
        self.clock.setProperty("fc", "muted")
        sh.nav_l.addWidget(self.clock)
        timer = QTimer(self, interval=15_000)
        timer.timeout.connect(self._tick)
        timer.start()
        self._tick()

        # üst çubuk
        self.eye = button("", "icon-btn", icon="eyeOff" if common.PRICES_HIDDEN else "eye", role="muted")
        self.eye.setCheckable(True)
        self.eye.setChecked(common.PRICES_HIDDEN)
        self.eye.toggled.connect(self._hide_prices)
        self.scan = button("", "icon-btn", icon="scan", role="muted", slot=self._scan)
        before = [self.eye, self.scan]
        if self.core.ann is not None:
            before.append(self.core.ann.button())
        self.tb = sh.topbar.mount(sync={"on_click": lambda st: self._sync_clicked()},
                                  lan={"on_click": lambda st: self._lan_clicked()} if self.lan is not None else False,
                                  update=self.core.updates, before=before)
        self._tips()
        fci.on_change(lambda l: self._tips())

        self.sync.state_changed.connect(self._sync_state)
        self.sync.data_changed.connect(self._remote_data)
        self._sync_state()
        if self.lan is not None:
            self.lan.state_changed.connect(self._lan_state)
            self._lan_state()

        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence.Find, self, activated=self._focus_search)
        QShortcut(QKeySequence.Undo, self, activated=self._undo)
        QShortcut(QKeySequence.New, self, activated=self._new)
        QShortcut(QKeySequence.Print, self, activated=lambda: (self.show_page(0), self.items_page.open_report()))
        self.show_page(0)

    # ------------------------------------------------------------ sayfalar
    @property
    def items_page(self):
        return self.items_host.page

    @property
    def contacts_page(self):
        return self.contacts_host.page

    @property
    def settings_page(self):
        return self.settings_host.page

    @property
    def pages(self):
        return [self.items_page, self.contacts_page, self.settings_page]

    def _settings_page(self):
        from .settings_page import SettingsPage
        p = SettingsPage(self.db, self.sync, self.ctl, self.lan)
        p.changed.connect(lambda: self.items_page.refresh())
        p.labels_changed.connect(self.ctl.labels_changed)
        return p

    def current_page(self):
        return self.pages[self.keys.index(self.shell.current or "items")]

    def show_page(self, i):
        self.shell.show_page(self.keys[i])

    def _page_changed(self, key):
        try:
            self.pages[self.keys.index(key)].refresh()
        except (RuntimeError, ValueError):
            pass

    def rebuild_pages(self):
        """Dil ya da etiketler değişince sayfa içeriklerini yeni yazılarla yeniden kurar (aynı sayfada kalır)."""
        for h in (self.items_host, self.contacts_host, self.settings_host):
            h.build()
        self.setWindowTitle(t("Organizer"))
        self._page_changed(self.shell.current or "items")
        self._tick()

    def _tips(self):
        self.eye.setToolTip(fci.t("org.eye"))
        self.scan.setToolTip(fci.t("org.scan"))
        self.shell.brand_name.setText(fci.t("org.name"))

    def _tick(self):
        loc = QLocale(QLocale.Arabic, QLocale.Syria) if i18n.is_rtl() else \
            QLocale(QLocale.English, QLocale.UnitedStates) if i18n.LANG == "en" else QLocale(QLocale.Turkish, QLocale.Turkey)
        self.clock.setText(loc.toString(QDateTime.currentDateTime(), "dddd\nd MMMM yyyy\nHH:mm").translate(ARABIC_DIGITS))

    def _focus_search(self):
        page = self.current_page()
        if hasattr(page, "search"):
            page.search.setFocus()
            page.search.selectAll()

    def _undo(self):
        p = self.current_page()
        if p is self.items_page and not p.search.hasFocus():
            p.undo()

    def _new(self):
        page = self.current_page()
        if page is self.items_page:
            page.new_item()
        elif page is self.contacts_page:
            page.new_contact()

    def _hide_prices(self, on):
        common.PRICES_HIDDEN = on
        self.db.set_setting("prices_hidden", "1" if on else "0")
        fcicons.set_icon(self.eye, "eyeOff" if on else "eye", "muted")
        for p in self.pages:
            p.refresh()

    def _scan(self):
        if self.current_page() is self.settings_page:
            self.show_page(0)
        self._focus_search()

    # ------------------------------------------------------------ bulut
    def _sync_clicked(self):
        if self.sync.is_connected():
            self.sync.sync_now()
        else:
            self.show_page(2)
            self.settings_page.open_account()

    def _sync_state(self, *_):
        s = self.sync
        if not s.is_connected():
            st = "off"
        elif s.busy():
            st = "syncing"
        elif s.last_error:
            st = "error"
        else:
            st = "idle"
        try:
            n = self.db.dirty_count() if st != "off" else 0
        except Exception:
            n = 0
        self.tb.set_sync(st, n)
        self.tb.sync_btn.setToolTip(s.status_text())

    def _remote_data(self):
        for p in self.pages:
            try:
                p.refresh()
            except RuntimeError:
                pass
        self._sync_state()

    # ------------------------------------------------------------ yerel ağ (Wi-Fi)
    def _lan_state(self, *_):
        busy = self.settings_page is not None and getattr(self.settings_page, "lan_busy", lambda: False)()
        self.tb.set_lan("busy" if busy else "on" if self.lan.running() else "off")
        self.tb.lan_btn.setToolTip(self.lan.status_text())

    def _lan_clicked(self):
        self.show_page(2)
        sp = self.settings_page
        if hasattr(sp, "show_lan"):
            sp.show_lan()

    # ------------------------------------------------------------ kapanış
    def closeEvent(self, e):
        if self.sync is not None and self.isVisible():
            try:
                self.tb.set_sync("syncing", 0)
                self.repaint()
            except RuntimeError:
                pass
            self.sync.finish()
        super().closeEvent(e)
