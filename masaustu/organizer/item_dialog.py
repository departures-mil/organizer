from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QCompleter, QFrame, QDateTimeEdit, QDialog, QDialogButtonBox,
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
        self.setStyleSheet("QListWidget { background: #f6f2ea; border-radius: 12px; }")

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

    def __init__(self, thumbs, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(t("Fotoğraflar"))
        lbl.setObjectName("SectionTitle")
        hint = QLabel(t("(sürükleyip bırakabilirsiniz)"))
        hint.setObjectName("Muted")
        add_photo = QPushButton(t("＋ Fotoğraf ekle"))
        add_photo.clicked.connect(self._pick_photos)
        fav = QPushButton(t("⭐ Favori yap"))
        fav.setToolTip(t("Seçili fotoğraf ilk sıraya alınır ve listede o görünür."))
        fav.clicked.connect(self._make_favorite)
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
        for i in range(self.list.count()):
            self.list.item(i).setText(t("⭐ Favori") if i == 0 and self.list.count() > 1 else "")

    def _pick_photos(self):
        files, _ = QFileDialog.getOpenFileNames(self, t("Fotoğraf seç"), str(Path.home()), photo_filter())
        self._add_photo_files(files)

    def _add_photo_files(self, files):
        for f in files:
            img = load_image(f, 256)
            self._add_entry(("new", f), QPixmap.fromImage(img))
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
        form.addRow(t("Adı:"), self.name)

        self.qty = QSpinBox()
        self.qty.setRange(0, 1_000_000)
        self.qty.setValue(1)
        self.qty.setSuffix(t(" adet"))
        self.qty.setMinimumWidth(140)
        form.addRow(t("Adet:"), self.qty)

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
        form.addRow(t("Dükkan adı:"), self.shop_name)
        self.shop_place = QLineEdit()
        self.shop_place.setPlaceholderText(t("Semt, çarşı, sokak ya da adres"))
        form.addRow(t("Dükkanın yeri:"), self.shop_place)
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

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(t("Ölçü, marka, nereden alındığı gibi notlar…"))
        self.notes.setFixedHeight(80)
        form.addRow(t("Notlar:"), self.notes)
        lay.addLayout(form)

        self.photos = PhotoEditor(thumbs)
        lay.addWidget(self.photos, 1)

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
            self.created.setDateTime(QDateTime.fromString(item["created_at"], "yyyy-MM-dd HH:mm:ss"))
            self.notes.setPlainText(item["notes"])
            self.photos.set_existing(item["photos"])
            self.shop_name.setText(item.get("shop_name") or "")
            self.shop_place.setText(item.get("shop_place") or "")
            self.shop_phone.setText(item.get("shop_phone") or "")
            self.channels.set_values(item)
        else:
            self.category.set_current_id(defaults.get("category_id"))
            self.location.set_current_id(defaults.get("location_id"))
        self.currency.setCurrentIndex(max(0, self.currency.findData(default_currency)))
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
        }

    def photo_entries(self):
        return self.photos.entries()


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
