from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFrame, QDateTimeEdit, QDialog, QDialogButtonBox, QTabWidget,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .common import PHOTO_EXTS, NewNodeDialog, TreeCombo, load_image, photo_filter, rounded
from .db import CURRENCIES
from .i18n import t
from .shop import ChannelPicker


class PhotoList(QListWidget):
    """Fotoğraf listesi; dosyalar sürükleyip bırakılarak da eklenebilir."""

    def __init__(self, on_files, parent=None):
        super().__init__(parent)
        self.on_files = on_files
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(110, 110))
        self.setGridSize(QSize(124, 124))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setObjectName("PhotoList")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            files = [u.toLocalFile() for u in e.mimeData().urls()
                     if Path(u.toLocalFile()).suffix.lower() in PHOTO_EXTS]
            self.on_files(files)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class PhotoEditor(QWidget):
    """Fotoğraf ekleme / kaldırma / favori seçme. İlk fotoğraf favoridir; listelerde o görünür."""

    def __init__(self, thumbs, parent=None, receipts=False, title=True):
        super().__init__(parent)
        self.thumbs = thumbs
        self.receipts = receipts   # v.1.0.8: fatura / fiş fotoğrafları (dosya adı "fis-" ile başlar)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(t("🧾  Fatura / fiş") if receipts else t("Fotoğraflar"))
        lbl.setObjectName("SectionTitle")
        lbl.setVisible(title)
        hint = QLabel(t("(sürükleyip bırakabilirsiniz)") if not receipts else
                      t("Faturanın, fişin ya da garanti belgesinin fotoğrafını ekleyin (sürükleyip bırakabilirsiniz)."))
        hint.setObjectName("Muted")
        add_photo = QPushButton(t("＋ Fiş / fatura ekle") if receipts else t("＋ Fotoğraf ekle"))
        add_photo.clicked.connect(self._pick_photos)
        fav = QPushButton(t("⭐ Favori yap"))
        fav.setToolTip(t("Seçili fotoğraf ilk sıraya alınır ve listede o görünür."))
        fav.clicked.connect(self._make_favorite)
        fav.setVisible(not receipts)
        del_photo = QPushButton(t("Seçileni kaldır"))
        del_photo.setObjectName("Danger")
        del_photo.clicked.connect(self._remove_photos)
        head.addWidget(lbl)
        head.addStretch()
        head.addWidget(add_photo)
        head.addWidget(fav)
        head.addWidget(del_photo)
        lay.addLayout(head)
        self.list = PhotoList(self._add_photo_files)
        self.list.itemDoubleClicked.connect(lambda *_: self._make_favorite())
        lay.addWidget(self.list, 1)
        lay.addWidget(hint)
        QShortcut(QKeySequence.Delete, self.list, activated=self._remove_photos)

    def set_existing(self, files):
        for f in files:
            self._add_entry(("existing", f), self.thumbs.pixmap(f))
        self._mark()

    def _add_entry(self, entry, pix):
        it = QListWidgetItem()
        it.setData(Qt.UserRole, entry)
        it.setData(Qt.UserRole + 1, pix)
        if not pix.isNull():
            it.setIcon(QIcon(rounded(pix, 110, 10)))
        it.setToolTip(Path(entry[1]).name)
        self.list.addItem(it)

    def _mark(self):
        if self.receipts:
            return
        for i in range(self.list.count()):
            self.list.item(i).setText(t("⭐ Favori") if i == 0 and self.list.count() > 1 else "")

    def _pick_photos(self):
        files, _ = QFileDialog.getOpenFileNames(self, t("Fotoğraf seç"), str(Path.home()), photo_filter())
        self._add_photo_files(files)

    def _add_photo_files(self, files):
        for f in files:
            img = load_image(f, 256)
            self._add_entry(("new_fis" if self.receipts else "new", f), QPixmap.fromImage(img))
        self._mark()

    def _remove_photos(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._mark()

    def _make_favorite(self):
        sel = self.list.selectedItems()
        if not sel:
            return
        it = self.list.takeItem(self.list.row(sel[0]))
        self.list.insertItem(0, it)
        self.list.setCurrentItem(it)
        self._mark()

    def entries(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


class ItemDialog(QDialog):
    def __init__(self, db, thumbs, item=None, defaults=None, parent=None):
        super().__init__(parent)
        self.db, self.thumbs, self.item = db, thumbs, item
        self.setWindowTitle(t("Eşyayı düzenle") if item else t("Yeni eşya"))
        self.setMinimumSize(780, 900)
        defaults = defaults or {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        title = QLabel(self.windowTitle())
        title.setObjectName("PageTitle")
        lay.addWidget(title)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Örn. 4x40 sunta vidası"))
        from .ek_arayuz import DateField, translate_button
        nrow = QHBoxLayout()
        nrow.addWidget(self.name, 1)
        nrow.addWidget(translate_button(self.name, self))
        form.addRow(t("Adı:"), nrow)

        self.qty = QSpinBox()
        self.qty.setRange(0, 1_000_000)
        self.qty.setValue(1)
        self.qty.setSuffix(t(" adet"))
        self.qty.setMinimumWidth(140)
        qrow = QHBoxLayout()
        qrow.addWidget(self.qty)
        qrow.addSpacing(18)
        ml = QLabel(t("En az adet:"))
        ml.setToolTip(t("Adet bunun altına düşünce eşya alışveriş listesine eklenir (0 = uyarı yok)"))
        self.min_qty = QSpinBox()
        self.min_qty.setRange(0, 1_000_000)
        self.min_qty.setSpecialValueText(t("Uyarı yok"))
        self.min_qty.setMinimumWidth(130)
        self.min_qty.setToolTip(ml.toolTip())
        qrow.addWidget(ml)
        qrow.addWidget(self.min_qty)
        qrow.addStretch()
        form.addRow(t("Adet:"), qrow)

        self.category = TreeCombo(db, "categories")
        form.addRow(t("Kategori:"), self._with_add(self.category, "categories"))
        self.location = TreeCombo(db, "locations")
        form.addRow(t("Bulunduğu yer:"), self._with_add(self.location, "locations"))

        price_row = QHBoxLayout()
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 1e12)
        self.price.setDecimals(2)
        self.price.setGroupSeparatorShown(True)
        self.price.setSpecialValueText("Belirtilmedi")
        self.price.setMinimumWidth(180)
        self.currency = QComboBox()
        for code, sym, name in CURRENCIES:
            self.currency.addItem(f"{sym}  {t(name)}", code)
        price_row.addWidget(self.price)
        price_row.addWidget(self.currency)
        price_row.addStretch()
        form.addRow(t("Alış fiyatı:"), price_row)
        # otomatik (tahmini) girilmiş fiyat: kullanıcı fiyatı değiştirince ya da işareti kaldırınca "sizin" olur
        self.price_auto = QCheckBox(t("⚡ Otomatik fiyat — henüz kontrol edilmedi"))
        self.price_auto.setToolTip(t("İşareti kaldırırsanız ya da fiyatı değiştirirseniz bu fiyat sizin girdiğiniz fiyat sayılır (✎)."))
        self.price_auto.setStyleSheet("color: #b7791f; font-weight: 600;")
        self.price_auto.hide()
        form.addRow("", self.price_auto)

        # ---- satın alındığı yer
        sep = QLabel(t("🏪  Satın alındığı yer"))
        sep.setObjectName("SectionTitle")
        form.addRow(sep)
        self.shops = db.known_shops()
        self.shop_name = QLineEdit()
        self.shop_name.setPlaceholderText(t("Örn. Yıldız Hırdavat"))
        comp = QCompleter(sorted(self.shops, key=str.lower), self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.activated.connect(self._fill_shop)
        self.shop_name.setCompleter(comp)
        self.shop_name.editingFinished.connect(lambda: self._fill_shop(self.shop_name.text()))
        form.addRow(t("Dükkan/Kişi Adı:"), self.shop_name)
        self.shop_place = QLineEdit()
        self.shop_place.setPlaceholderText(t("Semt, çarşı, sokak ya da adres"))
        form.addRow(t("Dükkan/Kişi Yeri:"), self.shop_place)
        phone_row = QHBoxLayout()
        self.shop_phone = QLineEdit()
        self.shop_phone.setLayoutDirection(Qt.LeftToRight)
        self.shop_phone.setPlaceholderText(t("Örn. 0532 123 45 67 ya da +963 …"))
        self.channels = ChannelPicker()
        phone_row.addWidget(self.shop_phone, 1)
        phone_row.addWidget(self.channels)
        form.addRow(t("İletişim numarası:"), phone_row)
        self.channel_status = QLabel()
        self.channel_status.setWordWrap(True)
        form.addRow("", self.channel_status)
        self.channels.changed.connect(self._draw_status)
        self.shop_phone.textChanged.connect(self._draw_status)

        self.created = QDateTimeEdit(QDateTime.currentDateTime())
        self.created.setCalendarPopup(True)
        self.created.setLayoutDirection(Qt.LeftToRight)
        self.created.setDisplayFormat("dd.MM.yyyy  HH:mm")
        self.created.setMinimumWidth(180)
        form.addRow(t("Ekleme tarihi:"), self.created)
        # 2.3.0: garanti bitişi ve son kullanma tarihi (yaklaşınca uyarı)
        self.warranty = DateField(t("var"))
        self.warranty.on.setToolTip(t("Garanti bitiş tarihini girin; yaklaşınca program hatırlatır."))
        form.addRow(t("Garanti bitişi:"), self.warranty)
        self.expiry = DateField(t("var"))
        self.expiry.on.setToolTip(t("İlaç, gıda, yangın tüpü, pil gibi eşyalarda son kullanma tarihi; yaklaşınca program hatırlatır."))
        form.addRow(t("Son kullanma tarihi:"), self.expiry)

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(t("Ölçü, marka, nereden alındığı gibi notlar…"))
        self.notes.setFixedHeight(80)
        notes_row = QHBoxLayout()
        notes_row.addWidget(self.notes, 1)
        notes_row.addWidget(translate_button(self.notes, self), 0, Qt.AlignTop)
        form.addRow(t("Notlar:"), notes_row)
        lay.addLayout(form)

        self.photos = PhotoEditor(thumbs, title=False)
        self.receipts = PhotoEditor(thumbs, receipts=True, title=False)
        self.ptabs = QTabWidget()
        self.ptabs.addTab(self.photos, t("📷  Fotoğraflar"))
        self.ptabs.addTab(self.receipts, t("🧾  Fatura / fiş"))
        ai_row = QHBoxLayout()
        self.ai_btn = QPushButton(t("✦  Fotoğraftan doldur (yapay zeka)"))
        self.ai_btn.setToolTip(t("İlk fotoğrafa bakarak ad, kategori, yer ve not önerir. Kendi yapay zeka anahtarınız gerekir "
                                 "(Ayarlar → Yapay zeka); internet olmadan çalışmaz."))
        self.ai_btn.clicked.connect(self._ai_fill)
        self.ai_msg = QLabel()
        self.ai_msg.setObjectName("Muted")
        self.ai_msg.setWordWrap(True)
        ai_row.addWidget(self.ai_btn)
        ai_row.addWidget(self.ai_msg, 1)
        lay.addLayout(ai_row)
        lay.addWidget(self.ptabs, 1)

        buttons = QDialogButtonBox()
        save = buttons.addButton(t("Kaydet"), QDialogButtonBox.AcceptRole)
        save.setObjectName("Primary")
        buttons.addButton(t("Vazgeç"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        default_currency = db.get_setting("default_currency", "TRY")
        if item:
            self.name.setText(item["name"])
            self.qty.setValue(item["quantity"])
            self.category.set_current_id(item["category_id"])
            self.location.set_current_id(item["location_id"])
            self.price.setValue(item["price"] or 0)
            default_currency = item["currency"]
            if item.get("price_auto") and item["price"] is not None:
                self.price_auto.setChecked(True)
                self.price_auto.show()
            self.created.setDateTime(QDateTime.fromString(item["created_at"], "yyyy-MM-dd HH:mm:ss"))
            self.notes.setPlainText(item["notes"])
            self.photos.set_existing(item["photos"])
            self.receipts.set_existing(item.get("receipts") or [])
            self.min_qty.setValue(int(item.get("min_qty") or 0))
            if item.get("receipts"):
                self.ptabs.setTabText(1, t("🧾  Fatura / fiş ({n})", n=len(item["receipts"])))
            self.shop_name.setText(item.get("shop_name") or "")
            self.shop_place.setText(item.get("shop_place") or "")
            self.shop_phone.setText(item.get("shop_phone") or "")
            self.channels.set_values(item)
            self.warranty.set_value(item.get("warranty_until") or "")
            self.expiry.set_value(item.get("expires_on") or "")
        else:
            self.category.set_current_id(defaults.get("category_id"))
            self.location.set_current_id(defaults.get("location_id"))
            if defaults.get("name"):          # sesle ekleme: "3 ampul ekle"
                self.name.setText(defaults["name"])
            if defaults.get("quantity"):
                self.qty.setValue(int(defaults["quantity"]))
        self.currency.setCurrentIndex(max(0, self.currency.findData(default_currency)))
        self.price.valueChanged.connect(lambda _: self.price_auto.setChecked(False))
        self.currency.currentIndexChanged.connect(lambda _: self.price_auto.setChecked(False))
        self._draw_status()
        self.name.setFocus()

    def _fill_shop(self, name):
        """Bilinen bir dükkan seçilince boş olan yer / numara / uygulama alanlarını doldurur."""
        info = self.shops.get((name or "").strip())
        if not info:
            return
        if not self.shop_place.text().strip():
            self.shop_place.setText(info["shop_place"])
        if not self.shop_phone.text().strip():
            self.shop_phone.setText(info["shop_phone"])
            self.channels.set_values(info)

    def _draw_status(self, *_):
        on = any(self.channels.values().values())
        self.channel_status.setText(self.channels.status_text(self.shop_phone.text()))
        self.channel_status.setStyleSheet(f"color: {'#1f9d55' if on else '#7b878d'}; font-weight: {700 if on else 400};")

    def _with_add(self, combo, table):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(combo, 1)
        btn = QPushButton(t("＋ Yeni"))
        btn.setToolTip(t("Yeni yer ekle") if table == "locations" else t("Yeni kategori ekle"))
        btn.clicked.connect(lambda: self._new_node(combo, table))
        h.addWidget(btn)
        return w

    def _new_node(self, combo, table):
        dlg = NewNodeDialog(self.db, table, combo.current_id(), self)
        if dlg.exec():
            name, parent_id = dlg.values()
            nid = self.db.add_node(table, name, parent_id)
            combo.reload(select=nid)

    def _save(self):
        if not self.name.text().strip():
            self.name.setFocus()
            self.name.setPlaceholderText(t("Lütfen bir ad yazın"))
            return
        self.accept()

    def data(self):
        price = self.price.value()
        return {
            "name": self.name.text().strip(),
            "quantity": self.qty.value(),
            "category_id": self.category.current_id(),
            "location_id": self.location.current_id(),
            "price": price if price > 0 else None,
            "currency": self.currency.currentData(),
            "notes": self.notes.toPlainText().strip(),
            "created_at": self.created.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "shop_name": self.shop_name.text().strip(),
            "shop_place": self.shop_place.text().strip(),
            "shop_phone": self.shop_phone.text().strip(),
            **self.channels.values(),
            "price_auto": not self.price_auto.isHidden() and self.price_auto.isChecked() and price > 0,
            "min_qty": self.min_qty.value(),
            "warranty_until": self.warranty.value(),
            "expires_on": self.expiry.value(),
        }

    # ---- 2.3.0: fotoğraftan öneri (çevrim içi yapay zeka)
    def _ai_fill(self):
        from . import i18n, zeka
        from .ek_arayuz import ai_error_text, run_async
        if not zeka.cfg():
            self.ai_msg.setText(ai_error_text(zeka.AiError("nokey")))
            return
        entries = self.photos.entries()
        if not entries:
            self.ai_msg.setText(t("Önce bir fotoğraf ekleyin."))
            return
        kind, value = entries[0]
        path = (self.db.photos_dir / value) if kind == "existing" else Path(value)
        img = load_image(path, 1024)
        if img.isNull():
            self.ai_msg.setText(t("Fotoğraf açılamadı"))
            return
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPEG", 85)
        data = bytes(buf.data())
        cats = [p for _i, _n, _d, p in self.db.tree_ordered("categories")]
        locs = [p for _i, _n, _d, p in self.db.tree_ordered("locations")]
        self.ai_btn.setEnabled(False)
        self.ai_msg.setText(t("Düşünüyor…"))

        def done(res):
            try:
                self.ai_btn.setEnabled(True)
                filled = []
                if res.get("name") and not self.name.text().strip():
                    self.name.setText(res["name"])
                    filled.append(t("ad"))
                elif res.get("name"):
                    filled.append(t("öneri: {x}", x=res["name"]))
                for key, combo, table in (("category", self.category, "categories"), ("location", self.location, "locations")):
                    if res.get(key) and combo.current_id() is None:
                        nid = next((i for i, _n, _d, p in self.db.tree_ordered(table) if p == res[key]), None)
                        if nid is not None:
                            combo.set_current_id(nid)
                            filled.append(t("kategori") if key == "category" else t("yer"))
                if res.get("notes") and not self.notes.toPlainText().strip():
                    self.notes.setPlainText(res["notes"])
                    filled.append(t("not"))
                self.ai_msg.setText(t("✦ Dolduruldu: {x} — kontrol edip kaydedin.", x=", ".join(filled)) if filled
                                    else t("✦ Öneri bulunamadı."))
            except RuntimeError:
                pass

        def failed(e):
            try:
                self.ai_btn.setEnabled(True)
                self.ai_msg.setText(ai_error_text(e))
            except RuntimeError:
                pass
        run_async(zeka.suggest_from_photo, done, failed, data, cats, locs, i18n.LANG)

    def photo_entries(self):
        return self.photos.entries() + self.receipts.entries()


class PhotoViewer(QDialog):
    """Fotoğrafları büyük gösterir; ok tuşlarıyla gezinilir."""

    def __init__(self, db, files, index=0, title="", parent=None):
        super().__init__(parent)
        self.db, self.files, self.index = db, files, index
        self.setWindowTitle(title or t("Fotoğraf"))
        self.setStyleSheet("QDialog { background: #1b2a30; } QLabel { color: white; }")
        lay = QVBoxLayout(self)
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setMinimumSize(400, 300)
        lay.addWidget(self.label, 1)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton(t("◀  Önceki"))
        self.next_btn = QPushButton(t("Sonraki  ▶"))
        self.counter = QLabel(alignment=Qt.AlignCenter)
        close = QPushButton(t("Kapat"))
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        close.clicked.connect(self.accept)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.counter, 1)
        nav.addWidget(self.next_btn)
        nav.addWidget(close)
        lay.addLayout(nav)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.step(1))
        self._pix = QPixmap()
        self._load()

    def step(self, d):
        if self.files:
            self.index = (self.index + d) % len(self.files)
            self._load()

    def _load(self):
        img = load_image(self.db.photos_dir / self.files[self.index], 2400)
        self._pix = QPixmap.fromImage(img)
        self.counter.setText(f"{self.index + 1} / {len(self.files)}")
        self.prev_btn.setEnabled(len(self.files) > 1)
        self.next_btn.setEnabled(len(self.files) > 1)
        self._show()

    def _show(self):
        if not self._pix.isNull():
            self.label.setPixmap(self._pix.scaled(self.label.size(), Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation))
        else:
            self.label.setText(t("Fotoğraf bulunamadı"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show()
