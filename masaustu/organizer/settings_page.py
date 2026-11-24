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
        cards += [self._data_card(), self._archive_card()]
        core = getattr(ctl, "core", None)
        about = {"version": __version__}
        if core is not None and core.updates is not None:
            about["on_check"] = lambda: core.updates.check()
        self.grid = fcsettings.build(cards=cards, usage={"firebase": True, "ai": False}, about=about,
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
        c.add(label(t("F11: tam ekran aç / kapat · Ctrl+F: ara · Ctrl+N: yeni kayıt · Ctrl+P: döküm"), "field-hint", wrap=True), 14)
        return c

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
        return c

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
        kinds = {"silindi": t("başka cihazda silindi"), "cakisma": t("çakışma yedeği"), "temizlendi": t("çöp kutusundan temizlendi")}
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


def fmt_ts(v):
    """ISO zaman (UTC) → yerel 'gg.aa.yyyy ss:dd'."""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone()
        return d.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(v or "")
