from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .common import Card, NewNodeDialog, confirm, info
from . import __version__, goster
from .db import CURRENCIES
from . import i18n
from .i18n import LANGUAGES, t


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


class SettingsPage(QWidget):
    changed = Signal()
    language_changed = Signal(str)
    labels_changed = Signal()
    theme_changed = Signal(str)

    def __init__(self, db, sync=None, updater=None, lan=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.sync = sync
        self.updater = updater
        self.lan = lan
        self._lan_worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        title = QLabel(t("Ayarlar"))
        title.setObjectName("PageTitle")
        root.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(16)
        self.locations = TreeEditor(db, "locations", t("🏠  Yerler"))
        self.categories = TreeEditor(db, "categories", t("🗂  Kategoriler"))
        for ed in (self.locations, self.categories):
            ed.changed.connect(self.changed)
            row.addWidget(ed, 1)

        general = Card()
        gl = QVBoxLayout(general)
        gl.setContentsMargins(18, 16, 18, 16)
        gt = QLabel(t("⚙  Genel"))
        gt.setObjectName("SectionTitle")
        gl.addWidget(gt)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.language = QComboBox()
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(i18n.LANG)))
        self.language.currentIndexChanged.connect(lambda _: self.language_changed.emit(self.language.currentData()))
        form.addRow(t("Dil:"), self.language)
        self.theme = QComboBox()
        for code, name in (("light", "☀  Açık"), ("dark", "🌙  Koyu"), ("auto", "🖥  Sistemle aynı")):
            self.theme.addItem(t(name), code)
        self.theme.setCurrentIndex(max(0, self.theme.findData(db.get_setting("theme", "light"))))
        self.theme.currentIndexChanged.connect(lambda _: self.theme_changed.emit(self.theme.currentData()))
        form.addRow(t("Görünüm:"), self.theme)
        self.currency = QComboBox()
        for code, sym, name in CURRENCIES:
            self.currency.addItem(f"{sym}  {t(name)}", code)
        self.currency.setCurrentIndex(max(0, self.currency.findData(db.get_setting("default_currency", "TRY"))))
        self.currency.currentIndexChanged.connect(
            lambda _: db.set_setting("default_currency", self.currency.currentData()))
        form.addRow(t("Varsayılan para birimi:"), self.currency)
        self.cc = QLineEdit(db.get_setting("country_code", "90"))
        self.cc.setMaximumWidth(90)
        self.cc.setToolTip(t("0 ile başlayan numaralara eklenecek ülke kodu (Türkiye 90, Suriye 963)"))
        self.cc.editingFinished.connect(self._save_cc)
        form.addRow(t("Ülke telefon kodu:"), self.cc)
        gl.addLayout(form)
        cc_hint = QLabel(t("WhatsApp / Telegram bağlantıları için kullanılır. "
                           "Numara + ile yazılmışsa kendi kodu geçerlidir."))
        cc_hint.setObjectName("Muted")
        cc_hint.setWordWrap(True)
        gl.addWidget(cc_hint)

        gl.addSpacing(14)
        lt = QLabel(t("🏷  Etiketler"))
        lt.setObjectName("SectionTitle")
        gl.addWidget(lt)
        lh = QLabel(t("Programdaki bütün yazıları (düğmeler, başlıklar, alan adları) kendinize göre değiştirebilirsiniz. "
                      "Değişiklik yalnızca seçili dil için geçerlidir."))
        lh.setObjectName("Muted")
        lh.setWordWrap(True)
        gl.addWidget(lh)
        from . import labels as _labels
        n = _labels.count()
        if n:
            ln = QLabel(t("{n} etiket değiştirildi", n=n))
            ln.setObjectName("Muted")
            gl.addWidget(ln)
        lbtn = QPushButton(t("🏷  Etiketleri düzenle…"))
        lbtn.clicked.connect(self._edit_labels)
        gl.addWidget(lbtn)

        if sync is not None:
            gl.addSpacing(14)
            ct = QLabel(t("☁  Bulut hesabı (Firebase)"))
            ct.setObjectName("SectionTitle")
            gl.addWidget(ct)
            self.cloud_status = QLabel()
            self.cloud_status.setObjectName("Muted")
            self.cloud_status.setWordWrap(True)
            gl.addWidget(self.cloud_status)
            crow = QHBoxLayout()
            self.account_btn = QPushButton()
            self.account_btn.clicked.connect(self.open_account)
            self.sync_btn = QPushButton(t("⟳  Şimdi eşitle"))
            self.sync_btn.clicked.connect(sync.sync_now)
            crow.addWidget(self.account_btn)
            crow.addWidget(self.sync_btn)
            gl.addLayout(crow)
            sync.state_changed.connect(self._cloud_state)
            self._cloud_state()

        if lan is not None:
            # ---- v.1.0.8: internet yokken aynı modem / router üzerinden eşitleme
            gl.addSpacing(14)
            lt2 = QLabel(t("📶  Yerel ağ eşitlemesi (internetsiz)"))
            lt2.setObjectName("SectionTitle")
            gl.addWidget(lt2)
            lh2 = QLabel(t("İnternet olmadığında telefon ve bilgisayarlar aynı modem / Wi-Fi üzerinden eşitlenir. "
                           "Kayıtlar bulut eşitlemesindeki gibi birleştirilir: her kaydın en son değiştirilen hali kalır, "
                           "hiçbir şey silinmez ya da üst üste yazılmaz. İnternet gelince değişiklikler buluta da gider."))
            lh2.setObjectName("Muted")
            lh2.setWordWrap(True)
            gl.addWidget(lh2)
            from PySide6.QtWidgets import QCheckBox
            self.lan_on = QCheckBox(t("Bu bilgisayar aynı ağdaki cihazlarla eşitlensin"))
            self.lan_on.setChecked(lan.enabled())
            self.lan_on.toggled.connect(lan.set_enabled)
            gl.addWidget(self.lan_on)
            self.lan_status = QLabel()
            self.lan_status.setObjectName("Muted")
            self.lan_status.setWordWrap(True)
            self.lan_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            gl.addWidget(self.lan_status)
            krow = QHBoxLayout()
            self.lan_code = QLabel()
            self.lan_code.setStyleSheet("font-size: 15pt; font-weight: 700; letter-spacing: 3px;")
            self.lan_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
            newk = QPushButton(t("Yeni kod"))
            newk.clicked.connect(lan.new_code)
            krow.addWidget(QLabel(t("Eşleme kodu:")))
            krow.addWidget(self.lan_code)
            krow.addStretch()
            krow.addWidget(newk)
            gl.addLayout(krow)
            kh = QLabel(t("Telefonda: Ayarlar → Yerel ağ eşitlemesi → „Bilgisayarı bul“. İlk seferde bu kod sorulur "
                          "(iki cihaz aynı bulut hesabındaysa sorulmaz). Windows güvenlik duvarı sorarsa „Erişime izin ver“ deyin."))
            kh.setObjectName("Muted")
            kh.setWordWrap(True)
            gl.addWidget(kh)
            self.lan_btn = QPushButton(t("🔍  Ağdaki başka bir bilgisayarla eşitle"))
            self.lan_btn.clicked.connect(self._lan_sync)
            gl.addWidget(self.lan_btn)
            lan.state_changed.connect(self._lan_state)
            self._lan_state()

        if updater is not None:
            gl.addSpacing(14)
            ut = QLabel(t("⬆  Güncelleme"))
            ut.setObjectName("SectionTitle")
            gl.addWidget(ut)
            self.update_status = QLabel()
            self.update_status.setObjectName("Muted")
            self.update_status.setWordWrap(True)
            gl.addWidget(self.update_status)
            # indirme sırasında: başlık + yüzde, ilerleme çubuğu ve alt alta düzenli bilgi satırları
            self.dl_box = QWidget()
            dv = QVBoxLayout(self.dl_box)
            dv.setContentsMargins(0, 4, 0, 4)
            dv.setSpacing(6)
            head = QHBoxLayout()
            self.dl_title = QLabel()
            self.dl_title.setStyleSheet("font-weight: 700;")
            self.dl_pct = QLabel()
            self.dl_pct.setStyleSheet("font-weight: 700;")
            self.dl_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            head.addWidget(self.dl_title, 1)
            head.addWidget(self.dl_pct)
            dv.addLayout(head)
            self.dl_bar = QProgressBar()
            self.dl_bar.setRange(0, 100)
            self.dl_bar.setTextVisible(False)
            self.dl_bar.setFixedHeight(8)
            dv.addWidget(self.dl_bar)
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(3)
            self.dl_rows = []
            for r in range(4):
                k, v = QLabel(), QLabel()
                k.setObjectName("Muted")
                v.setStyleSheet("font-weight: 600;")
                grid.addWidget(k, r, 0)
                grid.addWidget(v, r, 1)
                self.dl_rows.append((k, v))
            grid.setColumnStretch(1, 1)
            dv.addLayout(grid)
            self.dl_box.setVisible(False)
            gl.addWidget(self.dl_box)
            self.update_btn = QPushButton()
            self.update_btn.clicked.connect(self._update_clicked)
            gl.addWidget(self.update_btn)
            updater.changed.connect(self._update_state)
            self._update_state()

        gl.addSpacing(14)
        dt = QLabel(t("Veriler ve yedek"))
        dt.setObjectName("SectionTitle")
        gl.addWidget(dt)
        path = QLabel(str(db.data_dir))
        path.setObjectName("Muted")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gl.addWidget(path)
        open_btn = QPushButton(t("📂  Veri klasörünü aç"))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.data_dir))))
        backup_btn = QPushButton(t("💾  Yedek al (.zip)"))
        backup_btn.clicked.connect(self._backup)
        gl.addWidget(open_btn)
        gl.addWidget(backup_btn)

        # ---- v.1.0.10: kullanım limitleri (kendi Firebase hesabının günlük sınırı)
        gl.addSpacing(14)
        from . import kullanim_sayac
        gl.addWidget(kullanim_sayac.KullanimKarti(self))

        # ---- Asistan Agent (admin iletişimin önünde)
        from . import ajan as _ajan
        if _ajan.AJAN is not None:
            gl.addSpacing(14)
            gl.addWidget(_ajan.AJAN.card(self))

        # ---- v.1.0.8: admin ile iletişim (öneri / hata bildirimi)
        gl.addSpacing(14)
        at = QLabel(t("✉  Admin ile iletişime geç"))
        at.setObjectName("SectionTitle")
        gl.addWidget(at)
        ah = QLabel(t("Öneri, istek ya da hata bildirimlerinizi geliştiriciye gönderin; program sizin önerilerinizle gelişir."))
        ah.setObjectName("Muted")
        ah.setWordWrap(True)
        gl.addWidget(ah)
        fb = QPushButton(t("✉  Mesaj yaz…"))
        fb.setObjectName("Primary")
        fb.clicked.connect(self._feedback)
        gl.addWidget(fb)
        gl.addStretch()
        about = QLabel(t("Organizer {v}\nF11: tam ekran aç / kapat · Ctrl+F: ara · Ctrl+N: yeni kayıt · Ctrl+P: döküm", v=goster()))
        about.setObjectName("Muted")
        gl.addWidget(about)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(general)
        row.addWidget(scroll, 1)
        root.addLayout(row, 1)

    def _feedback(self):
        from .extras import FeedbackDialog
        FeedbackDialog(self).exec()

    def _lan_state(self, *_):
        self.lan_status.setText(self.lan.status_text())
        self.lan_code.setText(self.lan.code())
        busy = self._lan_worker is not None and self._lan_worker.isRunning()
        self.lan_btn.setEnabled(not busy)
        self.lan_btn.setText(t("⟳  Eşitleniyor…") if busy else t("🔍  Ağdaki başka bir bilgisayarla eşitle"))

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
            self.window()._remote_data()
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

    def _cloud_state(self, *_):
        connected = self.sync.is_connected()
        text = self.sync.status_text()
        if connected:
            text = t("Bağlı hesap: {e}", e=self.sync.email()) + "\n" + text
        self.cloud_status.setText(text)
        self.account_btn.setText(t("🔌  Hesabı kaldır") if connected else t("🔑  Hesaba bağlan"))
        self.sync_btn.setEnabled(connected and not self.sync.busy())

    def _update_state(self):
        u = self.updater
        v = u.version
        man = u.manifest or {}
        new = goster(man.get("surum", ""))
        btn, enabled, primary = t("🔄  Güncellemeleri denetle"), True, False
        if u.state == "checking":
            text, enabled = t("Sürüm {v} · Güncellemeler denetleniyor…", v=v), False
        elif u.state == "none":
            text = t("Sürüm {v} · Program güncel.", v=v)
        elif u.state == "available":
            text = t("Sürüm {v} · Yeni sürüm hazır: {n}", v=v, n=new)
            if man.get("notlar"):
                text += "\n" + man["notlar"]
            btn, primary = t("⬆  Şimdi güncelle ({n})", n=new), True
        elif u.state == "installing":
            text, enabled = t("Sürüm {v}", v=v), False
            btn = t("⬇  İndiriliyor %{p}", p=u.percent())
        elif u.state == "ready":
            text = t("{n} kuruldu. Program yeniden başlatılıyor…", n=goster(u.installed))
            btn, primary = t("↻  Yeniden başlat"), True
        elif u.state == "error":
            if u.message == "cloud":
                text = t("Sürüm {v} · Güncellemeler bulut hesabı üzerinden gelir; önce hesaba bağlanın.", v=v)
            elif u.message == "sistem":
                text = t("Sürüm {v} · {n} sürümü uygulama içinden kurulamıyor; yeni tam paket gerekiyor.", v=v, n=new)
            else:
                text = t("Sürüm {v}", v=v) + "\n⚠ " + u.message
        else:
            text = t("Sürüm {v}", v=v)
        self.update_status.setText(text)
        downloading = u.state == "installing"
        self.dl_box.setVisible(downloading)
        if downloading:
            from .updater import progress_rows
            self.dl_title.setText(t("Güncelleme indiriliyor: {n}", n=new))
            self.dl_pct.setText(f"%{u.percent()}")
            self.dl_bar.setValue(u.percent())
            for (k, v), (a, b) in zip(self.dl_rows, progress_rows(u)):
                k.setText(a)
                v.setText(b)
        self.update_btn.setText(btn)
        self.update_btn.setEnabled(enabled)
        self.update_btn.setObjectName("Primary" if primary else "")
        self.update_btn.style().unpolish(self.update_btn)
        self.update_btn.style().polish(self.update_btn)

    def _update_clicked(self):
        u = self.updater
        if u.state == "available":
            u.install()
        elif u.state == "ready":
            self.window().restart_for_update()
        else:
            u.check()

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
