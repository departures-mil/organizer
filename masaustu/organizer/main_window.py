from PySide6.QtCore import QDateTime, QLocale, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout)

from .contacts_page import ContactsPage
from . import common
from .topbar import TopBar
from .updater import fmt_mb, fmt_speed, fmt_eta
from . import i18n
from .i18n import t

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
from .items_page import ItemsPage
from .paths import asset
from .settings_page import SettingsPage
from .theme import BackgroundWidget


class MainWindow(QMainWindow):
    language_changed = Signal(str)

    def __init__(self, db, sync=None, updater=None):
        super().__init__()
        self.db = db
        self.sync = sync
        self.updater = updater
        self.setWindowTitle(t("Organizer"))
        self.setMinimumSize(1100, 700)

        central = BackgroundWidget()
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(20)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(280)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 26, 18, 20)
        sl.setSpacing(6)
        logo = QLabel(alignment=Qt.AlignCenter)
        logo.setPixmap(QPixmap(asset("logo.png")).scaled(112, 112, Qt.KeepAspectRatio,
                                                         Qt.SmoothTransformation))
        sl.addWidget(logo)
        name = QLabel(t("Organizer"), alignment=Qt.AlignCenter)
        name.setObjectName("AppTitle")
        sl.addWidget(name)
        sub = QLabel(t("Evdeki her şey yerli yerinde"), alignment=Qt.AlignCenter)
        sub.setObjectName("AppSubtitle")
        sl.addWidget(sub)
        sl.addSpacing(26)

        self.stack = QStackedWidget()
        self.items_page = ItemsPage(db)
        self.contacts_page = ContactsPage(db)
        self.settings_page = SettingsPage(db, sync, updater)
        self.settings_page.changed.connect(self.items_page.refresh)
        self.settings_page.language_changed.connect(self.language_changed)
        self.pages = [self.items_page, self.contacts_page, self.settings_page]
        for p in self.pages:
            self.stack.addWidget(p)

        group = QButtonGroup(self)
        group.setExclusive(True)
        self.nav = []
        for i, text in enumerate(["📦   Eşyalarım", "🔧   Ustalar && Dükkanlar", "⚙   Ayarlar"]):
            b = QPushButton(t(text))
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_page(i))
            group.addButton(b)
            sl.addWidget(b)
            self.nav.append(b)
        sl.addStretch()

        self.clock = QLabel(alignment=Qt.AlignCenter)
        self.clock.setObjectName("Clock")
        sl.addWidget(self.clock)
        self._locale = QLocale(QLocale.Arabic, QLocale.Syria) if i18n.is_rtl() else QLocale()
        timer = QTimer(self, interval=15_000)
        timer.timeout.connect(self._tick)
        timer.start()
        self._tick()
        sl.addSpacing(8)

        lay.addWidget(side)

        right = QVBoxLayout()
        right.setSpacing(14)
        self.topbar = TopBar(hidden=common.PRICES_HIDDEN)
        self.topbar.hide_toggled.connect(self._hide_prices)
        self.topbar.scan_clicked.connect(self._scan)
        self.topbar.language_changed.connect(self.language_changed)
        self.topbar.sync_clicked.connect(self._sync_clicked)
        self.topbar.update_clicked.connect(self._update_clicked)
        self.topbar.minimize_clicked.connect(self.showMinimized)
        self.topbar.size_clicked.connect(self.toggle_fullscreen)
        self.topbar.close_clicked.connect(self.close)
        right.addWidget(self.topbar)
        right.addWidget(self.stack, 1)
        lay.addLayout(right, 1)

        if sync is not None:
            sync.state_changed.connect(self._sync_state)
            sync.data_changed.connect(self._remote_data)
            self._sync_state(sync.status_text())
        else:
            self.topbar.sync_btn.hide()
        if updater is not None:
            updater.changed.connect(self._update_state)
            self._update_state()
        else:
            self.topbar.update_btn.hide()

        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence.Find, self, activated=self._focus_search)
        QShortcut(QKeySequence.New, self, activated=self._new)
        QShortcut(QKeySequence.Print, self, activated=lambda: (self.show_page(0), self.items_page.open_report()))
        self.show_page(0)

    def _tick(self):
        text = self._locale.toString(QDateTime.currentDateTime(), "dddd\nd MMMM yyyy\nHH:mm")
        self.clock.setText(text.translate(ARABIC_DIGITS))

    def show_page(self, i):
        self.nav[i].setChecked(True)
        self.stack.setCurrentIndex(i)
        self.pages[i].refresh()

    def _focus_search(self):
        page = self.stack.currentWidget()
        if hasattr(page, "search"):
            page.search.setFocus()
            page.search.selectAll()

    def _new(self):
        page = self.stack.currentWidget()
        if page is self.items_page:
            page.new_item()
        elif page is self.contacts_page:
            page.new_contact()

    def toggle_fullscreen(self):
        if self.isFullScreen() or self.isMaximized():
            self.showNormal()
            scr = self.screen().availableGeometry()
            w, h = max(1100, scr.width() // 2), max(700, int(scr.height() * 0.8))
            w, h = min(w, scr.width()), min(h, scr.height())
            self.setGeometry(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2, w, h)
        else:
            self.showFullScreen()

    def changeEvent(self, e):
        super().changeEvent(e)
        if hasattr(self, "topbar"):
            self.topbar.set_window_state(self.isFullScreen() or self.isMaximized())

    def _hide_prices(self, on):
        common.PRICES_HIDDEN = on
        self.db.set_setting("prices_hidden", "1" if on else "0")
        for p in self.pages:
            p.refresh()

    def _scan(self):
        if self.stack.currentWidget() is self.settings_page:
            self.show_page(0)
        self._focus_search()

    # ------------------------------------------------------------ bulut
    def _sync_clicked(self):
        if self.sync.is_connected():
            self.sync.sync_now()
        else:
            self.show_page(2)
            self.settings_page.open_account()

    def _sync_state(self, text):
        self.topbar.set_sync(text, self.sync.busy())
        self.topbar.set_info(text)

    def _remote_data(self):
        self.stack.currentWidget().refresh()
        if self.stack.currentWidget() is not self.items_page:
            self.items_page.refresh()

    # ------------------------------------------------------------ güncelleme
    def _update_state(self):
        u = self.updater
        new = (u.manifest or {}).get("surum", "")
        tb = self.topbar
        if u.state == "available":
            tb.set_update(t("Güncelle: {n}", n=new), t("Yeni sürüm hazır. Kurmak için tıklayın."), highlight=True)
        elif u.state == "installing":
            tb.set_update(t("%{p} · {a} / {b} MB · {s}", p=u.percent(), a=fmt_mb(u.done), b=fmt_mb(u.total),
                            s=fmt_speed(u.speed)),
                          t("Kalan: {k} MB · {e}", k=fmt_mb(max(u.total - u.done, 0)), e=fmt_eta(u.eta())),
                          highlight=True, enabled=True)
        elif u.state == "ready":
            tb.set_update(t("Yeniden başlatılıyor…"), enabled=False, highlight=True)
            QTimer.singleShot(1500, self.restart_for_update)
        elif u.state == "checking":
            tb.set_update(t("Denetleniyor…"), enabled=False)
        elif u.state == "none":
            tb.set_update(t("Güncelle"), t("Program güncel (sürüm {v}).", v=u.version))
        else:
            tb.set_update(t("Güncelle"), t("Yeni sürüm var mı diye bak (sürüm {v}).", v=u.version))

    def _update_clicked(self):
        u = self.updater
        if u.state == "available":
            self.show_page(2)          # indirme ayrıntıları (MB, kalan, hız, süre) Ayarlar'da da görünür
            u.install()
        elif u.state == "installing":
            self.show_page(2)
        elif u.state != "ready":
            u.check()

    def restart_for_update(self):
        """Güncelleme kuruldu: son eşitlemeyi yap, kapan ve yeni sürümle yeniden aç."""
        if getattr(self, "_restarting", False):
            return
        self._restarting = True
        from . import updater as upd
        from PySide6.QtWidgets import QApplication
        self.close()
        upd.restart()
        QApplication.quit()

    def closeEvent(self, e):
        if self.sync is not None and self.isVisible():
            self.topbar.set_info(t("Eşitleniyor…"))
            self.repaint()
            self.sync.finish()
        super().closeEvent(e)
