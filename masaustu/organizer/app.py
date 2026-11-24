"""Organizer masaüstü — açılış (2.2.0'dan beri ortak çekirdek fccore ile).

fccore.init: depo (veri klasörü/fccore/fccore.json, atomik), görünüm (Falcon + klasik + diğer şemalar, koyu/açık/otomatik,
yazı boyutu), iletişim kuyruğu, çökme raporu, güncelleme (GitHub Releases latest.json + FCD1 yama; win-app = fcpack zip,
win-setup = NSIS kurulum), "neler yeni", duyurular ve ilk açılış rehberi (Firebase adımıyla).
"""
import json
import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, i18n, theme
from .cloud import SyncManager
from .db import Database
from .paths import adopt_old_data, asset, data_dir

LOCALES = {
    "tr": QLocale(QLocale.Turkish, QLocale.Turkey),
    "en": QLocale(QLocale.English, QLocale.UnitedStates),
    # Arapçada da rakamlar 0-9 olarak gösterilsin (fiyat, adet ve tarih alanlarında karışmasın)
    "ar": QLocale(QLocale.English, QLocale.UnitedStates),
}

# "Bu sürümde neler yeni" (güncellemeden sonraki ilk açılış; latest.json notları yoksa bunlar gösterilir)
NEWS = {
    "2.2.3": {
        "tr": "- Eski sürümlerden bu sürüme geçiş bir kez tam kurulumla yapılır (eski güncelleyicideki siyah pencere sorunu yaşanmaz). Sonraki güncellemeler yine arka planda, kendiliğinden. Kayıtlar korunur.",
        "en": "- Moving from older versions to this one is done once with a full install (avoids the black-window problem of the old updater). Later updates again run by themselves in the background. Records are kept.",
        "ar": "- يتم الانتقال من الإصدارات القديمة إلى هذا الإصدار مرة واحدة بتثبيت كامل (تجنباً لمشكلة النوافذ السوداء في المحدِّث القديم). التحديثات اللاحقة تتم تلقائياً في الخلفية. تبقى السجلات محفوظة.",
    },
    "2.2.2": {
        "tr": "- Güncellemeler artık tamamen kendiliğinden: yeni sürüm arka planda sessizce indirilir, program kapanınca pencere açmadan kurulur; bir sonraki açılışta yeni sürüm gelir. Hemen kurmak için Güncelle → «Şimdi kur ve yeniden aç». Kurulum gereken güncellemeler de sessiz yapılır. Kayıtlara dokunulmaz.",
        "en": "- Updates are now fully automatic: the new version downloads quietly in the background and installs without any window when the program closes; the next start opens the new version. To install right away: Update → «Install now and reopen». Updates that need the installer also run silently. Records are not touched.",
        "ar": "- أصبحت التحديثات تلقائية بالكامل: يُنزَّل الإصدار الجديد بهدوء في الخلفية ويُثبَّت دون أي نافذة عند إغلاق البرنامج، ويُفتح الإصدار الجديد في المرة التالية. للتثبيت فوراً: تحديث ← «ثبّت الآن وأعد الفتح». التحديثات التي تحتاج إلى برنامج التثبيت تتم بصمت أيضاً. لا تُمَسّ السجلات.",
    },
    "2.2.1": {
        "tr": "- Telefon: dar ekranda (Arapça dahil) üst çubuktaki hiçbir düğme ekran dışında kalmaz\n"
              "- Masaüstü: eşya tablosunda Kategori sütunu varsayılan düzende görünür\n"
              "- Sürüm rozeti tam sürümü gösterir (v2.2.1)\n"
              "- Gizlilik: yönetici e-postası programda düz metin olarak tutulmaz",
        "en": "- Phone: no top bar button goes off-screen on narrow screens (including Arabic)\n"
              "- Desktop: the Category column is visible in the default items table layout\n"
              "- The version badge shows the full version (v2.2.1)\n"
              "- Privacy: the admin e-mail is no longer stored as plain text in the program",
        "ar": "- الهاتف: لا يخرج أي زر في الشريط العلوي عن الشاشة في الشاشات الضيقة (بما فيها العربية)\n"
              "- الحاسوب: يظهر عمود التصنيف في التخطيط الافتراضي لجدول الأغراض\n"
              "- تعرض شارة الإصدار رقم الإصدار كاملاً (v2.2.1)\n"
              "- الخصوصية: لم يعد البريد الإلكتروني للمشرف محفوظاً كنص صريح في البرنامج",
    },
    "2.2.0": {
        "tr": "- Yeni görünüm: Falcon şeması, renk şeması seçici (eski görünüm \"Klasik\" olarak duruyor), koyu/açık/otomatik ve yazı boyutu\n"
              "- Program artık kurulumla gelir; güncellemeler tek tıkla iner ve yalnızca değişen kısımlar indirilir (yüzde, MB, kalan, hız)\n"
              "- Eşitlemede hiçbir kayıt silinmez: başka cihazda silinen kayıt Arşiv'e alınır, çakışmada eski hal yedeklenir\n"
              "- İlk açılış rehberi, otomatik hata raporu, Kullanım Limitleri ve Admin ile iletişim yenilendi",
        "en": "- New look: Falcon scheme, colour scheme picker (the previous look is kept as \"Classic\"), dark/light/auto and font size\n"
              "- The program now comes with an installer; updates download with one click and only the changed parts are downloaded\n"
              "- Sync never deletes records: records deleted on another device are archived, older versions are backed up on conflicts\n"
              "- New setup guide, automatic error reports, Usage limits and Contact the admin",
        "ar": "- مظهر جديد: نظام Falcon، ومنتقي أنظمة الألوان (المظهر السابق باسم «الكلاسيكي»)، والوضع الداكن/الفاتح/التلقائي وحجم الخط\n"
              "- يأتي البرنامج الآن بمثبّت؛ تُنزَّل التحديثات بنقرة واحدة وتُنزَّل الأجزاء المتغيرة فقط\n"
              "- لا تحذف المزامنة أي سجل: السجلات المحذوفة على جهاز آخر تُؤرشف، وتُحفظ النسخة القديمة عند التعارض\n"
              "- دليل الإعداد الأول، وتقارير الأخطاء التلقائية، وحدود الاستخدام، والتواصل مع المشرف",
    },
}


class Controller:
    """Uygulama durumu: veritabanı, bulut, yerel ağ, çekirdek (güncelleme/duyurular) ve ana pencere."""

    def __init__(self, app, db, core):
        self.app, self.db, self.core = app, db, core
        self.translator = None
        self.win = None
        self._pending_fb = None
        self.sync = SyncManager(db)
        from .lan import LanServer
        self.lan = LanServer(db)
        # yerel ağ eşitlemesi: telefon bu bilgisayara bağlanıp kayıt gönderince listeler yenilensin
        self.lan.data_changed.connect(lambda: self.win and self.win._remote_data())
        self.sync.state_changed.connect(self._usage_project)
        self._usage_project()

    def _usage_project(self, *_):
        from fccore import usage
        try:
            usage.set_project((self.sync.config() or {}).get("projectId", "") if self.sync.is_connected() else "")
        except Exception:
            pass

    # ---- dil
    def apply_language(self, lang):
        i18n.set_language(lang)
        QLocale.setDefault(LOCALES[i18n.LANG])
        if self.translator:
            self.app.removeTranslator(self.translator)
        self.translator = QTranslator(self.app)
        if self.translator.load(f"qtbase_{i18n.LANG}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            self.app.installTranslator(self.translator)
        self.app.setApplicationDisplayName(i18n.t("Organizer"))

    def change_language(self, lang):
        old = i18n.LANG
        if lang == old:
            return
        self.db.set_setting("language", lang)
        self.db.translate_defaults(old, lang)
        self.apply_language(lang)
        if self.win is not None:
            self.win.rebuild_pages()

    def labels_changed(self):
        from . import labels
        labels.load(self.db)
        if self.win is not None:
            self.win.rebuild_pages()

    # ---- görünüm
    def apply_style(self, *_):
        from fccore import style
        theme.sync_dark()
        self.app.setStyleSheet(style.qss() + theme.compat_qss())
        if self.win is not None:
            for p in self.win.pages:
                try:
                    p.refresh()
                except Exception:
                    pass

    # ---- ilk açılış rehberi (Firebase adımı: kendi Firebase'iniz → ardından hesaba giriş)
    def onboarding_opts(self):
        return {"ai": False, "firebase": not self.sync.is_connected(), "on_firebase": self._on_firebase,
                "on_close": self._onboarding_closed}

    def _on_firebase(self, cfg, code):
        self._pending_fb = cfg

    def _onboarding_closed(self):
        cfg, self._pending_fb = self._pending_fb, None
        if not cfg or self.sync.is_connected():
            return
        self.db.set_setting("fb_config", json.dumps(cfg, indent=2))
        if self.win is not None:
            self.win.show_page(2)
            QTimer.singleShot(300, self.win.settings_page.open_account)

    # ---- pencere
    def build_window(self):
        from .main_window import MainWindow
        self.win = MainWindow(self)
        self.win.start()
        from . import ajan
        ajan.pencere(self.app, self.win, True)


def _seed_core_storage(db):
    """2.1'den gelen kullanıcı: dil ve koyu/açık seçimi çekirdeğe taşınır; rehber yerine "neler yeni" gösterilir."""
    from fccore import storage
    if storage.get("lang") is None:
        storage.set("lang", db.get_setting("language", "tr") or "tr")
    old_user = bool(db.get_setting("sync_last") or db.get_setting("fb_refresh") or db.count_items())
    if storage.get("theme") is None:
        old = db.get_setting("theme", "")
        if old in ("light", "dark", "auto"):
            storage.set("theme", old)
        elif old_user:
            storage.set("theme", "light")        # 2.1'in varsayılanı açıktı
    if old_user:
        if storage.get("onboarding.done") is None:
            storage.set("onboarding.done", True)
        if storage.get("whatsnew.seen") is None:
            storage.set("whatsnew.seen", "2.1.0")
    if storage.get("firebase.config") is None and db.get_setting("fb_config"):
        try:
            storage.set("firebase.config", json.loads(db.get_setting("fb_config")))
        except Exception:
            pass


def run():
    if sys.platform == "win32":
        try:  # görev çubuğunda kendi logosunu göstermesi için
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Organizer.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Organizer")
    app.setWindowIcon(QIcon(asset("logo.png")))
    app.setStyle("Fusion")

    folder = data_dir()
    adopt_old_data(folder)
    db = Database(folder)
    try:
        db.purge_old_trash()   # çöp kutusunda 30 günü dolanlar arşive alınıp listeden kalkar
    except Exception:
        pass

    import fccore
    from fccore import i18n as fci, storage, style, whatsnew
    core_dir = str(folder / "fccore")
    os.makedirs(core_dir, exist_ok=True)
    storage.use(core_dir, app="organizer")
    _seed_core_storage(db)
    theme.register_klasik()
    whatsnew.cfg["notes"] = lambda v: NEWS.get(str(v))
    core = fccore.init(app, app_id="organizer", repo="organizer", version=__version__, data_dir=core_dir,
                       announcements=True, onboarding=None, agent=False)   # kendi Asistan Agent bağlantısı: organizer/ajan.py

    from . import ajan
    ajan.kur(app)
    ctl = Controller(app, db, core)
    from . import common
    common.PRICES_HIDDEN = db.get_setting("prices_hidden", "0") == "1"
    from . import labels
    labels.load(db)
    ctl.apply_language(fci.lang())
    fci.on_change(ctl.change_language)
    style.on_change(ctl.apply_style)
    ctl.apply_style()
    ctl.build_window()
    os.environ["ORGANIZER_BASLADI"] = "1"
    core.after_show()
    if not core.whatsnew_shown:
        from fccore import onboarding
        QTimer.singleShot(700, lambda: onboarding.maybe_start(**ctl.onboarding_opts()))
    QTimer.singleShot(1500, ctl.sync.sync_now)  # açılışta buluttan son hali al
    QTimer.singleShot(2500, ctl.lan.start)      # yerel ağ eşitlemesi (internetsiz) için bekle
    # 2.1'den kalan, gönderilemeyen eski iletişim mesajları (varsa) bir kez daha denenir
    from .extras import outbox_flush
    QTimer.singleShot(20000, lambda: outbox_flush(db))
    return app.exec()

