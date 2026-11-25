from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .common import Card, NewNodeDialog, confirm, info
from . import __version__
from .db import CURRENCIES
from .i18n import t


class DragTree(QTreeWidget):
    moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setIndentation(18)
        self.setAnimated(True)

    def dropEvent(self, e):
        super().dropEvent(e)
        self.moved.emit()


class TreeEditor(Card):
    """Yerler ya da kategoriler için ekle / alt öğe ekle / yeniden adlandır / sil."""
    changed = Signal()

    def __init__(self, db, table, title, parent=None):
        super().__init__(parent)
        self.db, self.table = db, table
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        lay.addWidget(heading)
        hint = QLabel(t("Sürükleyip bırakarak sırasını ya da üst öğesini değiştirebilirsiniz. "
                        "Çift tıklayarak yeniden adlandırabilirsiniz."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = DragTree()
        self.tree.moved.connect(self._save_structure)
        self.tree.itemDoubleClicked.connect(lambda *_: self.rename())
        lay.addWidget(self.tree, 1)

        grid = QGridLayout()
        add = QPushButton(t("＋ Ekle"))
        add.setObjectName("Primary")
        add.clicked.connect(lambda: self.add(child=False))
        sub = QPushButton(t("＋ Alt öğe ekle"))
        sub.clicked.connect(lambda: self.add(child=True))
        ren = QPushButton(t("✎ Yeniden adlandır"))
        ren.clicked.connect(self.rename)
        dele = QPushButton(t("Sil"))
        dele.setObjectName("Danger")
        dele.clicked.connect(self.delete)
        grid.addWidget(add, 0, 0)
        grid.addWidget(sub, 0, 1)
        grid.addWidget(ren, 1, 0)
        grid.addWidget(dele, 1, 1)
        lay.addLayout(grid)

    def reload(self, select=None):
        if select is None and self.tree.currentItem():
            select = self.tree.currentItem().data(0, Qt.UserRole)
        self.tree.clear()
        counts = self.db.item_counts(self.table)
        items = {}
        for nid, name, depth, path in self.db.tree_ordered(self.table):
            n = counts.get(nid, 0)
            it = QTreeWidgetItem([t("{name}   ·  {n} eşya", name=name, n=n) if n else name])
            it.setData(0, Qt.UserRole, nid)
            it.setData(0, Qt.UserRole + 1, name)
            it.setFlags(it.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
            items[nid] = it
        for r in self.db.tree_rows(self.table):
            it = items[r["id"]]
            parent = items.get(r["parent_id"])
            (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
        # tree_rows sırası sort'a göre; ekleme sırası korunur
        self.tree.expandAll()
        if select in items:
            self.tree.setCurrentItem(items[select])

    def _current(self):
        it = self.tree.currentItem()
        return (it.data(0, Qt.UserRole), it.data(0, Qt.UserRole + 1)) if it else (None, None)

    def add(self, child):
        nid, _ = self._current()
        if child and nid is None:
            info(self, t("Alt öğe ekle"), t("Önce listeden bir yer seçin.") if self.table == "locations" else t("Önce listeden bir kategori seçin."))
            return
        dlg = NewNodeDialog(self.db, self.table, nid if child else None, self)
        if dlg.exec():
            name, parent_id = dlg.values()
            new_id = self.db.add_node(self.table, name, parent_id)
            self.reload(select=new_id)
            self.changed.emit()

    def rename(self):
        nid, name = self._current()
        if nid is None:
            return
        text, ok = QInputDialog.getText(self, t("Yeniden adlandır"), t("Yeni ad:"), QLineEdit.Normal, name)
        if ok and text.strip():
            self.db.rename_node(self.table, nid, text)
            self.reload(select=nid)
            self.changed.emit()

    def delete(self):
        nid, name = self._current()
        if nid is None:
            return
        n = self.db.items_under(self.table, nid)
        has_children = self.tree.currentItem().childCount() > 0
        text = t("„{name}“ ve altındaki her şey silinsin mi?\n" if has_children else "„{name}“ silinsin mi?\n", name=name)
        if n:
            text += t("\nBurada kayıtlı {n} eşya silinmeyecek; bir üst öğeye taşınacak.", n=n)
        if confirm(self, t("Sil"), text, yes=t("Sil"), danger=True):
            self.db.delete_node(self.table, nid)
            self.reload()
            self.changed.emit()

    def _save_structure(self):
        entries = []

        def walk(parent_item, parent_id):
            count = parent_item.childCount() if parent_item else self.tree.topLevelItemCount()
            for i in range(count):
                it = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                nid = it.data(0, Qt.UserRole)
                entries.append((nid, parent_id, i))
                walk(it, nid)

        walk(None, None)
        self.db.set_structure(self.table, entries)
        self.changed.emit()




class SettingsPage(QScrollArea):
    """Ayarlar: üstte Yerler + Kategoriler; altında ortak çekirdek ayar ızgarası:
    Görünüm (çekirdek) · Genel · Bulut hesabı · Yerel ağ · Veriler ve yedek · Arşiv · Asistan Agent ·
    Kullanım Limitleri · Otomatik hata raporu · Hakkında (güncelleme) · Admin ile iletişim (HER ZAMAN SON)."""
    changed = Signal()
    labels_changed = Signal()

    def __init__(self, db, sync=None, ctl=None, lan=None, parent=None):
        super().__init__(parent)
        self.db, self.sync, self.ctl, self.lan = db, sync, ctl, lan
        self._lan_worker = None
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("fcContent")
        self.setWidget(host)
        self.viewport().setAutoFillBackground(False)
        root = QVBoxLayout(host)
        root.setContentsMargins(0, 0, 6, 20)
        root.setSpacing(18)

        row = QHBoxLayout()
        row.setSpacing(18)
        self.locations = TreeEditor(db, "locations", t("🏠  Yerler"))
        self.categories = TreeEditor(db, "categories", t("🗂  Kategoriler"))
        for ed in (self.locations, self.categories):
            ed.setMinimumHeight(380)
            ed.changed.connect(self.changed)
            row.addWidget(ed, 1)
        root.addLayout(row)

        from fccore import settings as fcsettings
        cards = [self._general_card()]
        if sync is not None:
            cards.append(self._cloud_card())
        if lan is not None:
            cards.append(self._lan_card())
        cards += [self._data_card(), self._ai_card(), self._archive_card()]
        core = getattr(ctl, "core", None)
        about = {"version": __version__}
        if core is not None and core.updates is not None:
            about["on_check"] = lambda: core.updates.check()
        self.grid = fcsettings.build(cards=cards, usage={"firebase": True, "ai": True}, about=about,
                                     onboarding=ctl.onboarding_opts() if ctl is not None else None)
        from . import ajan as _ajan
        if _ajan.AJAN is not None:
            try:
                self.grid.add(_ajan.AJAN.card(self))      # iletişim kartının önüne
            except Exception:
                pass
        root.addWidget(self.grid)
        root.addStretch(1)

    # ------------------------------------------------------------ kartlar
    @staticmethod
    def _card(title, icon, desc=None):
        from fccore.widgets import Card as FcCard
        return FcCard("", title, icon, desc)

    def _general_card(self):
        from fccore.widgets import field, label
        db = self.db
        c = self._card(t("⚙  Genel").replace("⚙", "").strip(), "settings")
        self.currency = QComboBox()
        for code, sym, name in CURRENCIES:
            self.currency.addItem(f"{sym}  {t(name)}", code)
        self.currency.setCurrentIndex(max(0, self.currency.findData(db.get_setting("default_currency", "TRY"))))
        self.currency.currentIndexChanged.connect(lambda _: db.set_setting("default_currency", self.currency.currentData()))
        c.add(field(t("Varsayılan para birimi:").rstrip(":"), self.currency))
        self.cc = QLineEdit(db.get_setting("country_code", "90"))
        self.cc.setMaximumWidth(110)
        self.cc.setToolTip(t("0 ile başlayan numaralara eklenecek ülke kodu (Türkiye 90, Suriye 963)"))
        self.cc.editingFinished.connect(self._save_cc)
        c.add(field(t("Ülke telefon kodu:").rstrip(":"), self.cc,
                    t("WhatsApp / Telegram bağlantıları için kullanılır. Numara + ile yazılmışsa kendi kodu geçerlidir.")))
        c.add(label(t("🏷  Etiketler"), "fc-sub"), 16)
        c.add(label(t("Programdaki bütün yazıları (düğmeler, başlıklar, alan adları) kendinize göre değiştirebilirsiniz. "
                      "Değişiklik yalnızca seçili dil için geçerlidir."), "card-desc", wrap=True), 6)
        from . import labels as _labels
        n = _labels.count()
        if n:
            c.add(label(t("{n} etiket değiştirildi", n=n), "muted"), 4)
        lbtn = QPushButton(t("🏷  Etiketleri düzenle…"))
        lbtn.setProperty("fc", "btn small")
        lbtn.clicked.connect(self._edit_labels)
        c.add(lbtn, 8)
        # ---- 2.3.0: hatırlatma süresi · cihaz adı · açılış sayfası
        from PySide6.QtWidgets import QSpinBox
        self.warn = QSpinBox()
        self.warn.setRange(1, 365)
        self.warn.setSuffix(t(" gün"))
        self.warn.setValue(int(db.get_setting("warn_days", "30") or 30))
        self.warn.setMaximumWidth(140)
        self.warn.valueChanged.connect(lambda v: (db.set_setting("warn_days", str(v)), self.changed.emit()))
        c.add(field(t("Garanti / son kullanma hatırlatması:"), self.warn,
                    t("Bitişine bu kadar gün kala Ana sayfada ve açılışta hatırlatılır.")))
        self.devname = QLineEdit(db.device_name())
        self.devname.setMaximumWidth(260)
        self.devname.editingFinished.connect(lambda: db.set_setting("device_name", self.devname.text().strip()))
        c.add(field(t("Bu cihazın adı:"), self.devname, t("Değişiklik geçmişinde „kim, hangi cihazdan“ olarak görünür.")))
        self.start = QComboBox()
        self.start.addItem(fci_t("org.panel"), "panel")
        self.start.addItem(t("Eşyalarım"), "items")
        self.start.setCurrentIndex(max(0, self.start.findData(db.get_setting("start_page", "panel"))))
        self.start.currentIndexChanged.connect(lambda _: db.set_setting("start_page", self.start.currentData()))
        self.start.setMaximumWidth(260)
        c.add(field(t("Açılışta gösterilecek sayfa:"), self.start))
        c.add(label(t("F11: tam ekran aç / kapat · Ctrl+F: ara · Ctrl+N: yeni kayıt · Ctrl+P: döküm"), "field-hint", wrap=True), 14)
        return c

    # ------------------------------------------------------------ 2.3.0: yapay zeka
    def _ai_card(self):
        from fccore.widgets import field, hbox, label
        from . import zeka
        c = self._card(t("Yapay zeka (çevrim içi + çevrim dışı)"), "sparkles",
                       t("Asistan, fotoğraftan doldurma ve daha iyi çeviri için KENDİ ücretsiz anahtarınızı girin; "
                         "programı dağıtan kişinin limitleri kullanılmaz. Anahtar yalnızca bu cihazda saklanır. "
                         "İnternet ya da anahtar yoksa Asistan cihazdaki kayıtlardan, çeviri çevrim dışı sözlükten çalışır."))
        cur = zeka.cfg() or {}
        try:
            from fccore import storage
            raw = storage.get("ai") or {}
        except Exception:
            raw = {}
        self.ai_prov = QComboBox()
        for pid, name, *_ in zeka.PROVIDERS:
            self.ai_prov.addItem(name, pid)
        self.ai_prov.setCurrentIndex(max(0, self.ai_prov.findData(raw.get("provider") or "gemini")))
        c.add(field(t("Sağlayıcı:"), self.ai_prov, t("Google Gemini'nin ücretsiz kotası çoğu kullanım için yeterlidir.")))
        self.ai_key = QLineEdit(raw.get("key") or "")
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText(t("API anahtarı"))
        self.ai_key.setLayoutDirection(Qt.LeftToRight)
        get = QPushButton(t("Anahtar al ↗"))
        get.setProperty("fc", "btn small")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(zeka.provider_info(self.ai_prov.currentData())[4])))
        c.add(field(t("Anahtar:"), hbox(self.ai_key, get)))
        self.ai_model = QLineEdit(raw.get("model") or "")
        self.ai_model.setPlaceholderText(t("boş = varsayılan ({m})", m=zeka.provider_info(self.ai_prov.currentData())[2]))
        self.ai_model.setLayoutDirection(Qt.LeftToRight)
        self.ai_prov.currentIndexChanged.connect(lambda _: self.ai_model.setPlaceholderText(
            t("boş = varsayılan ({m})", m=zeka.provider_info(self.ai_prov.currentData())[2])))
        c.add(field(t("Model (isteğe bağlı):"), self.ai_model))
        self.ai_status = label(t("Durum: anahtar girilmiş ✓") if cur else t("Durum: anahtar yok — çevrim dışı çalışır"), "muted", wrap=True)
        save = QPushButton(t("Kaydet"))
        save.setProperty("fc", "btn small primary")
        save.clicked.connect(self._ai_save)
        test = QPushButton(t("Dene"))
        test.setProperty("fc", "btn small")
        test.clicked.connect(self._ai_test)
        c.add(hbox(save, test, None), 12)
        c.add(self.ai_status, 8)
        c.add(label(t("Günlük yapay zeka çağrıları „Kullanım Limitleri“ kartında görünür."), "field-hint", wrap=True), 6)
        return c

    def _ai_save(self):
        from . import zeka
        zeka.set_cfg(self.ai_prov.currentData(), self.ai_key.text(), self.ai_model.text())
        self.ai_status.setText(t("Durum: anahtar girilmiş ✓") if zeka.cfg() else t("Durum: anahtar yok — çevrim dışı çalışır"))

    def _ai_test(self):
        from . import zeka
        from .ek_arayuz import ai_error_text, run_async
        self._ai_save()
        if not zeka.cfg():
            return
        self.ai_status.setText(t("Deneniyor…"))

        def ok(text):
            try:
                self.ai_status.setText(t("✓ Çalışıyor: {x}", x=text[:80]))
            except RuntimeError:
                pass

        def bad(e):
            try:
                self.ai_status.setText("⚠ " + ai_error_text(e))
            except RuntimeError:
                pass
        run_async(zeka.call, ok, bad, "Reply with just the word: OK", None, "image/jpeg", 10)

    def _cloud_card(self):
        from fccore.widgets import hbox, label
        c = self._card(t("☁  Bulut hesabı (Firebase)").replace("☁", "").strip(), "cloud")
        self.cloud_status = label("", "card-desc", wrap=True)
        c.add(self.cloud_status)
        self.account_btn = QPushButton()
        self.account_btn.setProperty("fc", "btn small")
        self.account_btn.clicked.connect(self.open_account)
        self.sync_btn = QPushButton(t("⟳  Şimdi eşitle"))
        self.sync_btn.setProperty("fc", "btn small primary")
        self.sync_btn.clicked.connect(self.sync.sync_now)
        c.add(hbox(self.account_btn, self.sync_btn, None), 12)
        c.add(label(t("Kayıtlar eşitlenirken hiçbir kayıt silinmez ya da üstüne yazılmaz: başka cihazda silinen kayıt "
                      "bu cihazda Arşiv'e alınır, çakışmada eski hal çakışma yedeğine kaydedilir."), "field-hint", wrap=True), 12)
        self.sync.state_changed.connect(self._cloud_state)
        self._cloud_state()
        return c

    def _lan_card(self):
        from PySide6.QtWidgets import QCheckBox
        from fccore.widgets import hbox, label
        lan = self.lan
        c = self._card(t("📶  Yerel ağ eşitlemesi (internetsiz)").replace("📶", "").strip(), "wifi",
                       t("İnternet olmadığında telefon ve bilgisayarlar aynı modem / Wi-Fi üzerinden eşitlenir. "
                         "Kayıtlar bulut eşitlemesindeki gibi birleştirilir: her kaydın en son değiştirilen hali kalır, "
                         "hiçbir şey silinmez ya da üst üste yazılmaz. İnternet gelince değişiklikler buluta da gider."))
        self.lan_card = c
        self.lan_on = QCheckBox(t("Bu bilgisayar aynı ağdaki cihazlarla eşitlensin"))
        self.lan_on.setChecked(lan.enabled())
        self.lan_on.toggled.connect(lan.set_enabled)
        c.add(self.lan_on, 10)
        self.lan_status = label("", "muted", wrap=True)
        self.lan_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.add(self.lan_status, 6)
        self.lan_code = QLabel()
        self.lan_code.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 3px;")
        self.lan_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        newk = QPushButton(t("Yeni kod"))
        newk.setProperty("fc", "btn small")
        newk.clicked.connect(lan.new_code)
        c.add(hbox(QLabel(t("Eşleme kodu:")), self.lan_code, None, newk), 8)
        c.add(label(t("Telefonda: Ayarlar → Yerel ağ eşitlemesi → „Bilgisayarı bul“. İlk seferde bu kod sorulur "
                      "(iki cihaz aynı bulut hesabındaysa sorulmaz). Windows güvenlik duvarı sorarsa „Erişime izin ver“ deyin."),
                    "field-hint", wrap=True), 6)
        self.lan_btn = QPushButton(t("🔍  Ağdaki başka bir bilgisayarla eşitle"))
        self.lan_btn.setProperty("fc", "btn small primary")
        self.lan_btn.clicked.connect(lambda: self._lan_sync())
        c.add(self.lan_btn, 10)
        lan.state_changed.connect(self._lan_state)
        self._lan_state()
        return c

    def _data_card(self):
        from fccore.widgets import label
        db = self.db
        c = self._card(t("Veriler ve yedek"), "download")
        path = label(str(db.data_dir), "muted", wrap=True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.add(path)
        open_btn = QPushButton(t("📂  Veri klasörünü aç"))
        open_btn.setProperty("fc", "btn small")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.data_dir))))
        backup_btn = QPushButton(t("💾  Yedek al (.zip)"))
        backup_btn.setProperty("fc", "btn small")
        backup_btn.clicked.connect(self._backup)
        c.add(open_btn, 10)
        c.add(backup_btn, 8)
        restore_btn = QPushButton(t("♻  Yedekten geri yükle…"))
        restore_btn.setProperty("fc", "btn small")
        restore_btn.clicked.connect(self._restore_backup)
        c.add(restore_btn, 8)
        # ---- 2.3.0: otomatik yedek
        from fccore.widgets import field, hbox
        from . import yedek
        st = yedek.settings(db)
        c.add(label(t("Otomatik yedek"), "fc-sub"), 18)
        self.ab_freq = QComboBox()
        for k, v in (("off", t("Kapalı")), ("daily", t("Her gün")), ("weekly", t("Her hafta"))):
            self.ab_freq.addItem(v, k)
        self.ab_freq.setCurrentIndex(max(0, self.ab_freq.findData(st["freq"])))
        self.ab_freq.currentIndexChanged.connect(lambda _: (yedek.save_settings(db, freq=self.ab_freq.currentData()),
                                                            self._ab_draw()))
        c.add(field(t("Sıklık:"), self.ab_freq))
        self.ab_dir = label(st["dir"], "muted", wrap=True)
        self.ab_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pick = QPushButton(t("📁  Klasör seç…"))
        pick.setProperty("fc", "btn small")
        pick.clicked.connect(self._ab_pick)
        reset = QPushButton(t("Varsayılan"))
        reset.setProperty("fc", "btn small")
        reset.clicked.connect(lambda: (yedek.save_settings(db, folder=yedek.default_dir(db)), self._ab_draw()))
        c.add(field(t("Yedek klasörü:"), self.ab_dir,
                    t("Google Drive'a gitsin isterseniz bilgisayarınızdaki Google Drive klasörünü seçin "
                      "(Google Drive masaüstü uygulaması o klasörü kendiliğinden Drive'a yükler).")))
        c.add(hbox(pick, reset, None), 6)
        from PySide6.QtWidgets import QSpinBox
        self.ab_keep = QSpinBox()
        self.ab_keep.setRange(1, 100)
        self.ab_keep.setValue(st["keep"])
        self.ab_keep.setMaximumWidth(120)
        self.ab_keep.valueChanged.connect(lambda v: yedek.save_settings(db, keep=v))
        c.add(field(t("Saklanacak yedek sayısı:"), self.ab_keep, t("Daha eskileri kendiliğinden silinir.")))
        self.ab_pw = QLineEdit(st["password"])
        self.ab_pw.setEchoMode(QLineEdit.Password)
        self.ab_pw.setPlaceholderText(t("boş = şifresiz"))
        self.ab_pw.setMaximumWidth(260)
        self.ab_pw.editingFinished.connect(lambda: yedek.save_settings(db, password=self.ab_pw.text()))
        c.add(field(t("Yedek şifresi (isteğe bağlı):"), self.ab_pw,
                    t("Şifreli yedek (.ozb) AES-256 ile korunur; şifreyi unutursanız yedek açılamaz.")))
        self.ab_status = label("", "muted", wrap=True)
        now_btn = QPushButton(t("💾  Şimdi otomatik yedek al"))
        now_btn.setProperty("fc", "btn small primary")
        now_btn.clicked.connect(self._ab_now)
        c.add(now_btn, 10)
        c.add(self.ab_status, 6)
        self._ab_draw()
        return c

    def _ab_draw(self):
        from . import yedek
        st = yedek.settings(self.db)
        try:
            self.ab_dir.setText(st["dir"])
            files = yedek.list_backups(st["dir"])
            last = fmt_ts_local(st["last"]) if st["last"] else t("henüz yok")
            self.ab_status.setText(t("Son otomatik yedek: {x}", x=last) + " · " + t("{n} yedek dosyası", n=len(files)) +
                                   ("" if st["freq"] != "off" else " · " + t("otomatik yedek kapalı")))
        except RuntimeError:
            pass

    def _ab_pick(self):
        from . import yedek
        d = QFileDialog.getExistingDirectory(self, t("Yedek klasörü"), yedek.settings(self.db)["dir"])
        if d:
            yedek.save_settings(self.db, folder=d)
            self._ab_draw()

    def _ab_now(self):
        from . import yedek
        from .ek_arayuz import run_async
        yedek.save_settings(self.db, password=self.ab_pw.text())
        st = yedek.settings(self.db)
        self.ab_status.setText(t("Yedek alınıyor…"))

        def done(path):
            self.db.set_setting("auto_backup_last", datetime.now().isoformat(timespec="seconds"))
            self._ab_draw()
            info(self, t("Yedek alındı"), t("Yedek kaydedildi:\n{path}", path=path))

        def failed(e):
            try:
                self.ab_status.setText(t("Yedek alınamadı: {m}", m=e))
            except RuntimeError:
                pass
        run_async(yedek.run, done, failed, self.db, None, st)

    def _restore_backup(self):
        from . import yedek
        target, _ = QFileDialog.getOpenFileName(self, t("Yedekten geri yükle"), str(Path(yedek.settings(self.db)["dir"])),
                                                t("Organizer yedeği") + " (*.zip *.ozb)")
        if not target:
            return
        pw = None
        while True:
            try:
                data = yedek.read(target, pw)
                break
            except yedek.NeedPassword:
                pw, ok = QInputDialog.getText(self, t("Yedek şifresi"), t("Bu yedek şifreli. Şifreyi yazın:"), QLineEdit.Password)
                if not ok:
                    return
            except yedek.WrongPassword:
                pw, ok = QInputDialog.getText(self, t("Yedek şifresi"), t("Şifre yanlış. Yeniden yazın:"), QLineEdit.Password)
                if not ok:
                    return
            except (yedek.BadBackup, OSError) as e:
                info(self, t("Yedekten geri yükle"), t("Bu dosya bir Organizer yedeği değil ya da bozuk. ({m})", m=e))
                return
        if not confirm(self, t("Yedekten geri yükle"),
                       t("Yedekteki kayıtlar geri getirilsin mi?\n\n• Hiçbir kayıt silinmez: şu anki farklı haller Arşiv'e alınır, "
                         "yedekte olmayan kayıtlar yerinde kalır.\n• Başlamadan önce şu anki halin yedeği alınır.\n"
                         "• Bulut bağlıysa geri gelen kayıtlar öbür cihazlara da gider."), yes=t("Geri yükle")):
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            counts = yedek.restore(self.db, data)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            info(self, t("Yedekten geri yükle"), t("Geri yüklenemedi: {m}", m=e))
            return
        QApplication.restoreOverrideCursor()
        self.changed.emit()
        self.refresh()
        win = self.window()
        if hasattr(win, "_remote_data"):
            win._remote_data()
        info(self, t("Yedekten geri yükle"), t("Geri yüklendi.") + "\n" + yedek.summary(counts, t))
        if self.sync is not None and self.sync.is_connected():
            self.sync.sync_now()

    def _archive_card(self):
        """Başka cihazda silinen kayıtlar ve çakışma yedekleri (eşitleme kuralı: hiçbir şey kalıcı silinmez)."""
        from fccore.widgets import label
        c = self._card(t("Arşiv ve çakışma yedekleri"), "archive",
                       t("Başka cihazda silinen kayıtlar bu cihazda silinmez, burada arşivlenir. Eşitlemede üstüne "
                         "yazılan değişikliklerinizin eski hali de burada durur. İstediğinizi geri alabilirsiniz."))
        self.archive_box = QWidget()
        self.archive_lay = QVBoxLayout(self.archive_box)
        self.archive_lay.setContentsMargins(0, 0, 0, 0)
        self.archive_lay.setSpacing(6)
        c.add(self.archive_box, 10)
        self._archive_draw()
        return c

    def _archive_draw(self):
        from fccore.widgets import hbox, label
        lay = self.archive_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        try:
            rows = self.db.archive_list(30)
            total = self.db.archive_count()
        except Exception:
            rows, total = [], 0
        if not rows:
            lay.addWidget(label(t("Arşivde kayıt yok."), "muted"))
            return
        kinds = {"silindi": t("başka cihazda silindi"), "cakisma": t("çakışma yedeği"), "temizlendi": t("çöp kutusundan temizlendi"),
                 "yedek_oncesi": t("yedekten geri yüklemeden önceki hali")}
        tables = {"items": t("Eşya"), "contacts": t("Usta / dükkan"), "locations": t("Yer"), "categories": t("Kategori")}
        for r in rows:
            name = r["name"] or "—"
            txt = label(f"{tables.get(r['table'], r['table'])}: {name}\n{kinds.get(r['kind'], r['kind'])} · {fmt_ts(r['at'])}",
                        "muted", wrap=True)
            b = QPushButton(t("Geri al"))
            b.setProperty("fc", "btn small")
            b.clicked.connect(lambda _=False, i=r["id"], n=name: self._restore(i, n))
            row = hbox(txt, None, b)
            row.setProperty("fc", "fc-li")
            lay.addWidget(row)
        if total > len(rows):
            lay.addWidget(label(t("… ve {n} kayıt daha", n=total - len(rows)), "muted"))

    def _restore(self, aid, name):
        try:
            self.db.archive_restore(aid)
        except Exception as e:  # noqa: BLE001
            info(self, t("Arşiv ve çakışma yedekleri"), str(e))
            return
        from fccore.widgets import toast
        toast(t("Geri alındı: {s}", s=name), "", 4000)
        self._archive_draw()
        self.changed.emit()
        if self.sync is not None and self.sync.is_connected():
            self.sync.sync_now()

    def refresh_archive(self):
        if not hasattr(self, "archive_lay"):
            return
        try:
            self._archive_draw()
        except RuntimeError:
            pass

    # ------------------------------------------------------------ yerel ağ
    def lan_busy(self):
        return self._lan_worker is not None and self._lan_worker.isRunning()

    def show_lan(self):
        if getattr(self, "lan_card", None) is not None:
            self.ensureWidgetVisible(self.lan_card, 0, 40)

    def _lan_state(self, *_):
        try:
            self.lan_status.setText(self.lan.status_text())
            self.lan_code.setText(self.lan.code())
            busy = self.lan_busy()
            self.lan_btn.setEnabled(not busy)
            self.lan_btn.setText(t("⟳  Eşitleniyor…") if busy else t("🔍  Ağdaki başka bir bilgisayarla eşitle"))
        except RuntimeError:
            return
        w = self.window()
        if hasattr(w, "_lan_state") and w is not self:
            w._lan_state()

    def _lan_sync(self, host=None, port=None, name=None):
        from PySide6.QtWidgets import QApplication
        from . import lan as L
        if host is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                found = L.discover()
            finally:
                QApplication.restoreOverrideCursor()
            last = self.db.get_setting("lan_peer", "")
            if not found:
                text, ok = QInputDialog.getText(self, t("Yerel ağ eşitlemesi"),
                                                t("Aynı ağda açık bir Organizer bilgisayarı bulunamadı.\n"
                                                  "Öbür bilgisayarın adresini biliyorsanız yazın (ör. 192.168.1.20):"),
                                                QLineEdit.Normal, last.split(":")[0] if last else "")
                if not ok or not text.strip():
                    return
                host, port, name = text.strip().split(":")[0], L.HTTP_PORT, text.strip()
            elif len(found) == 1:
                host, port, name = found[0]["host"], found[0]["port"], found[0]["name"]
            else:
                labels = [f"{f['name']}  ({f['host']})" for f in found]
                choice, ok = QInputDialog.getItem(self, t("Yerel ağ eşitlemesi"), t("Hangi bilgisayarla eşitlensin?"),
                                                  labels, 0, False)
                if not ok:
                    return
                f = found[labels.index(choice)]
                host, port, name = f["host"], f["port"], f["name"]
        key = self.db.get_setting(f"lan_key_{host}") or L.uid_key(self.db.get_setting("fb_uid"))
        if not key:
            key = self._ask_code(name)
            if not key:
                return
        self._start_lan(host, port, name, key)

    def _ask_code(self, name):
        code, ok = QInputDialog.getText(self, t("Eşleme kodu"),
                                        t("{name} bilgisayarının Ayarlar → Yerel ağ eşitlemesi bölümündeki 6 haneli kodu yazın:",
                                          name=name))
        return "".join(ch for ch in code if ch.isdigit()) if ok else ""

    def _start_lan(self, host, port, name, key):
        from .lan import LanClientWorker
        w = LanClientWorker(self.db.data_dir, host, port, key)
        self._lan_worker = w

        def done(res):
            self.db.set_setting(f"lan_key_{host}", key)
            self.db.set_setting("lan_peer", f"{host}:{port}")
            self._lan_state()
            self.changed.emit()
            win = self.window()
            if hasattr(win, "_remote_data"):
                win._remote_data()
            self.refresh_archive()
            info(self, t("Yerel ağ eşitlemesi"), t("{name} ile eşitlendi.\n{a} kayıt alındı · {b} fotoğraf gönderildi · {c} fotoğraf alındı.",
                                                    name=name, a=res["received"], b=res["sent"], c=res["photos"]))

        def failed(code, detail):
            self._lan_state()
            if code == "key":
                self.db.set_setting(f"lan_key_{host}", None)
                key2 = self._ask_code(name)
                if key2:
                    self._start_lan(host, port, name, key2)
                return
            info(self, t("Yerel ağ eşitlemesi"), t("Eşitlenemedi: {m}", m=detail or code))

        w.done.connect(done)
        w.failed.connect(failed)
        w.finished.connect(self._lan_state)
        w.start()
        self._lan_state()

    # ------------------------------------------------------------ bulut
    def _cloud_state(self, *_):
        try:
            connected = self.sync.is_connected()
            text = self.sync.status_text()
            if connected:
                text = t("Bağlı hesap: {e}", e=self.sync.email()) + "\n" + text
            self.cloud_status.setText(text)
            self.account_btn.setText(t("🔌  Hesabı kaldır") if connected else t("🔑  Hesaba bağlan"))
            self.sync_btn.setEnabled(connected and not self.sync.busy())
        except RuntimeError:
            return
        if not self.sync.busy():
            self.refresh_archive()

    def open_account(self):
        if self.sync is None:
            return
        if self.sync.is_connected():
            if confirm(self, t("Hesabı kaldır"),
                       t("Bu bilgisayar bulut hesabından ayrılsın mı?\nBilgisayardaki kayıtlar silinmez."),
                       yes=t("Hesabı kaldır"), danger=True):
                self.sync.disconnect_account()
            return
        from .cloud import AccountDialog
        AccountDialog(self.sync, self).exec()

    # ------------------------------------------------------------ diğer
    def _edit_labels(self):
        from .labels import LabelEditor
        if LabelEditor(self.db, self).exec():
            self.labels_changed.emit()

    def _save_cc(self):
        digits = "".join(ch for ch in self.cc.text() if ch.isdigit()) or "90"
        self.cc.setText(digits)
        self.db.set_setting("country_code", digits)

    def _backup(self):
        default = Path.home() / f"Organizer-yedek-{datetime.now():%Y-%m-%d}.zip"
        target, _ = QFileDialog.getSaveFileName(self, t("Yedeği kaydet"), str(default), t("Zip dosyası") + " (*.zip)")
        if target:
            out = self.db.backup(Path(target))
            info(self, t("Yedek alındı"), t("Yedek kaydedildi:\n{path}", path=out))

    def refresh(self):
        self.locations.reload()
        self.categories.reload()
        self.refresh_archive()


def fci_t(key):
    from fccore import i18n as fci
    return fci.t(key)


def fmt_ts_local(v):
    """Yerel ISO zaman → 'gg.aa.yyyy ss:dd'."""
    try:
        return datetime.fromisoformat(str(v)).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(v or "")


def fmt_ts(v):
    """ISO zaman (UTC) → yerel 'gg.aa.yyyy ss:dd'."""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone()
        return d.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(v or "")
