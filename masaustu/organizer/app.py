import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from . import i18n
from .cloud import SyncManager
from .db import Database
from .i18n import t
from .main_window import MainWindow
from .paths import adopt_old_data, asset, data_dir
from . import theme
from .theme import build_style
from .updater import Updater

LOCALES = {
    "tr": QLocale(QLocale.Turkish, QLocale.Turkey),
    "en": QLocale(QLocale.English, QLocale.UnitedStates),
    # Arapçada da rakamlar 0-9 olarak gösterilsin (fiyat, adet ve tarih alanlarında karışmasın)
    "ar": QLocale(QLocale.English, QLocale.UnitedStates),
}


class Controller:
    """Dili uygular ve dil değişince ana pencereyi yeniden kurar."""

    def __init__(self, app, db):
        self.app, self.db = app, db
        self.translator = None
        self.win = None
        from . import kullanim_sayac, i18n as _i18n
        kullanim_sayac.baslat(str(db.data_dir), dil=lambda: _i18n.LANG, bulut=True, ai=False,
                              proje=lambda: ((self.sync.config() or {}).get("projectId", "") if self.sync.is_connected() else ""))
        self.sync = SyncManager(db)
        self.updater = Updater(self.sync)
        self._checked_update = False
        self.sync.state_changed.connect(self._after_sync)
        from .lan import LanServer
        self.lan = LanServer(db)
        # yerel ağ eşitlemesi: internet yoksa (bulut hatası ağ kaynaklıysa) telefon bu bilgisayara bağlanır
        self.lan.data_changed.connect(lambda: self.win and self.win._remote_data())

    def _after_sync(self, _text=""):
        """İlk başarılı eşitlemeden sonra bir kez yeni sürüm var mı diye bak."""
        if not self._checked_update and self.sync.is_connected() and not self.sync.busy() \
                and not self.sync.last_error and self.db.get_setting("sync_last"):
            self._checked_update = True
            self.updater.check()

    def check_update_once(self):
        if not self._checked_update:
            self._checked_update = True
            self.updater.check()

    def apply_language(self, lang):
        i18n.set_language(lang)
        QLocale.setDefault(LOCALES[i18n.LANG])
        if self.translator:
            self.app.removeTranslator(self.translator)
        self.translator = QTranslator(self.app)
        if self.translator.load(f"qtbase_{i18n.LANG}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            self.app.installTranslator(self.translator)
        self.app.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.app.setApplicationDisplayName(t("Organizer"))
        self.apply_theme()

    def apply_theme(self):
        """Açık / koyu görünüm (Ayarlar → Görünüm; "auto" = Windows'un ayarı)."""
        theme.DARK = theme.resolve_dark(self.db.get_setting("theme", "light"))
        pal = QPalette()
        if theme.DARK:
            for role, c in ((QPalette.Window, "#111a1e"), (QPalette.WindowText, "#e2ebee"), (QPalette.Base, "#18242a"),
                            (QPalette.AlternateBase, "#1d2a30"), (QPalette.Text, "#e2ebee"), (QPalette.Button, "#1d2a30"),
                            (QPalette.ButtonText, "#e2ebee"), (QPalette.ToolTipBase, "#1d5f74"),
                            (QPalette.ToolTipText, "#ffffff"), (QPalette.Highlight, "#2a9d8f"),
                            (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#7d939b"),
                            (QPalette.Link, "#7fd1c5")):
                pal.setColor(role, QColor(c))
        else:
            pal = self.app.style().standardPalette()
        self.app.setPalette(pal)
        self.app.setStyleSheet(build_style(i18n.is_rtl(), theme.DARK))

    def change_theme(self, mode):
        self.db.set_setting("theme", mode)
        self.apply_theme()
        self.rebuild()

    def build_window(self, page=0, fullscreen=True, maximized=False):
        old = self.win
        self.win = MainWindow(self.db, self.sync, self.updater, self.lan)
        self.win.language_changed.connect(self.change_language)
        self.win.theme_changed.connect(self.change_theme)
        self.win.labels_changed.connect(self.rebuild)
        self.win.show_page(page)
        if fullscreen:
            self.win.showFullScreen()
        elif maximized:
            self.win.showMaximized()
        else:
            self.win.show()
        from . import ajan
        ajan.pencere(self.app, self.win, old is None)
        if old is not None:
            old.hide()
            old.deleteLater()

    def rebuild(self):
        """Etiketler değişince pencereyi yeni yazılarla yeniden kurar (aynı sayfada kalır)."""
        state = (self.win.isFullScreen(), self.win.isMaximized())
        geo = self.win.geometry()
        page = self.win.stack.currentIndex()
        self.app.setApplicationDisplayName(t("Organizer"))
        self.build_window(page=page, fullscreen=state[0], maximized=state[1])
        if not state[0] and not state[1]:
            self.win.setGeometry(geo)

    def change_language(self, lang):
        old_lang = i18n.LANG
        if lang == old_lang:
            return
        self.db.set_setting("language", lang)
        self.db.translate_defaults(old_lang, lang)
        state = (self.win.isFullScreen(), self.win.isMaximized())
        geo = self.win.geometry()
        page = self.win.stack.currentIndex()
        self.apply_language(lang)
        self.build_window(page=page, fullscreen=state[0], maximized=state[1])
        if not state[0] and not state[1]:
            self.win.setGeometry(geo)


def run():
    if sys.platform == "win32":
        try:  # görev çubuğunda kendi logosunu göstermesi için
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Organizer.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Organizer")
    app.setWindowIcon(QIcon(asset("logo.png")))
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))

    folder = data_dir()
    adopt_old_data(folder)
    db = Database(folder)
    try:
        db.purge_old_trash()   # çöp kutusunda 30 günü dolanlar kalıcı silinir
    except Exception:
        pass
    from . import ajan
    ajan.kur(app)
    ctl = Controller(app, db)
    from . import common
    common.PRICES_HIDDEN = db.get_setting("prices_hidden", "0") == "1"
    from . import labels
    labels.load(db)
    ctl.apply_language(db.get_setting("language", "tr"))
    ctl.build_window()
    os.environ["ORGANIZER_BASLADI"] = "1"   # main.py: pencere açıldı, güncelleme sağlam
    QTimer.singleShot(1500, ctl.sync.sync_now)  # açılışta buluttan son hali al
    QTimer.singleShot(2500, ctl.lan.start)      # yerel ağ eşitlemesi (internetsiz) için bekle
    QTimer.singleShot(4000, ctl.check_update_once)  # güncellemeler GitHub'dan: bulut hesabı beklenmez
    return app.exec()
