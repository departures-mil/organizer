from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .common import Card, HeaderSort, ThumbCache, confirm, setup_columns
from .db import phone_for_links
from .item_dialog import PhotoEditor, PhotoViewer
from .professions import ProfessionIcons
from . import i18n
from .i18n import PROFESSIONS, t
from .paths import asset


CHANNELS = [
    ("has_whatsapp", "whatsapp", "WhatsApp"),
    ("has_telegram", "telegram", "Telegram"),
    ("has_call", "call", "Telefonla arama"),
]


def channel_icon(key):
    return QIcon(asset(f"{key}.png"))


def open_channel(key, phone, country_code):
    digits = phone_for_links(phone, country_code)
    if not digits:
        return
    url = {"whatsapp": f"https://wa.me/{digits}",
           "telegram": f"https://t.me/+{digits}",
           "call": f"tel:+{digits}"}[key]
    QDesktopServices.openUrl(QUrl(url))


class ChannelCell(QWidget):
    """Telefonun yanındaki WhatsApp / Telegram / Arama simgeleri.
    Renkli olanlar çalışır, soluk olanlar kullanılmıyor demektir."""

    def __init__(self, contact, country_code, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        for field, key, label in CHANNELS:
            b = QToolButton()
            b.setIcon(channel_icon(key))
            b.setIconSize(QSize(28, 28))
            on = bool(contact[field]) and bool(contact["phone"])
            b.setEnabled(on)
            b.setToolTip(t("{label} ile ulaş", label=t(label)) if on else t("{label} yok", label=t(label)))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: open_channel(k, contact["phone"], country_code))
            lay.addWidget(b)
        lay.addStretch()


class ContactDialog(QDialog):
    def __init__(self, db, thumbs, icons, contact=None, parent=None):
        super().__init__(parent)
        self.icons = icons
        self.setWindowTitle(t("Kişiyi düzenle") if contact else t("Yeni usta / dükkan"))
        self.setMinimumSize(720, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        title = QLabel(self.windowTitle())
        title.setObjectName("PageTitle")
        lay.addWidget(title)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        kind_row = QHBoxLayout()
        kind_row.setSpacing(22)
        self.r_usta = QRadioButton(t("🔧  Usta"))
        self.r_shop = QRadioButton(t("🏪  Dükkan"))
        self.r_usta.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_usta)
        grp.addButton(self.r_shop)
        kind_row.addWidget(self.r_usta)
        kind_row.addWidget(self.r_shop)
        kind_row.addStretch()
        form.addRow(t("Tür:"), kind_row)

        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Örn. Ahmet Usta / Yıldız Hırdavat"))
        form.addRow(t("İsim:"), self.name)
        self.profession = QComboBox()
        self.profession.setEditable(True)
        self.profession.setIconSize(QSize(26, 26))
        for name in PROFESSIONS[i18n.LANG] + [p for p in db.professions() if p not in PROFESSIONS[i18n.LANG]]:
            self.profession.addItem(icons.icon(name, "usta", 26), name)
        self.profession.setCurrentText("")
        self.profession.lineEdit().setPlaceholderText(t("Örn. Elektrikçi, Tesisatçı, Nalbur"))
        self.prof_icon = QLabel()
        self.prof_icon.setFixedSize(36, 36)
        self.prof_icon.setToolTip(t("Mesleğin simgesi. Yeni bir meslek yazarsanız uygun simge internetten kendiliğinden bulunur."))
        prof_row = QHBoxLayout()
        prof_row.addWidget(self.prof_icon)
        prof_row.addWidget(self.profession, 1)
        form.addRow(t("Meslek / alan:"), prof_row)
        self.place = QLineEdit()
        self.place.setPlaceholderText(t("Semt, sokak ya da adres"))
        form.addRow(t("Yer / adres:"), self.place)
        self.phone = QLineEdit()
        self.phone.setLayoutDirection(Qt.LeftToRight)
        self.phone.setPlaceholderText(t("Örn. 0532 123 45 67 ya da +963 …"))
        form.addRow(t("Telefon:"), self.phone)

        ch_row = QHBoxLayout()
        ch_row.setSpacing(22)
        self.checks = {}
        for field, key, label in CHANNELS:
            cb = QCheckBox(label if key != "call" else t("Arama"))
            cb.setIcon(channel_icon(key))
            cb.setIconSize(QSize(24, 24))
            self.checks[field] = cb
            ch_row.addWidget(cb)
        ch_row.addStretch()
        form.addRow(t("Ulaşılabilir:"), ch_row)
        hint = QLabel(t("Numaranın hangi uygulamalarda çalıştığını işaretleyin."))
        hint.setObjectName("Muted")
        form.addRow("", hint)

        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(80)
        self.notes.setPlaceholderText(t("Çalışma saatleri, fiyat, tavsiye eden kişi…"))
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

        if contact:
            (self.r_shop if contact["kind"] == "dukkan" else self.r_usta).setChecked(True)
            self.name.setText(contact["name"])
            self.profession.setCurrentText(contact["profession"])
            self.place.setText(contact["place"])
            self.phone.setText(contact["phone"])
            self.notes.setPlainText(contact["notes"])
            for field, cb in self.checks.items():
                cb.setChecked(bool(contact[field]))
            self.photos.set_existing(contact.get("photos") or [])
        else:
            self.checks["has_call"].setChecked(True)
        self.profession.currentTextChanged.connect(self._update_icon)
        self.r_shop.toggled.connect(self._update_icon)
        icons.changed.connect(self._update_icon)
        self._update_icon()

    def _update_icon(self, *_):
        kind = "dukkan" if self.r_shop.isChecked() else "usta"
        self.prof_icon.setPixmap(self.icons.pixmap(self.profession.currentText().strip(), kind, 36))

    def photo_entries(self):
        return self.photos.entries()

    def _save(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def data(self):
        d = {
            "kind": "dukkan" if self.r_shop.isChecked() else "usta",
            "name": self.name.text().strip(),
            "profession": self.profession.currentText().strip(),
            "place": self.place.text().strip(),
            "phone": self.phone.text().strip(),
            "notes": self.notes.toPlainText().strip(),
        }
        for field, cb in self.checks.items():
            d[field] = int(cb.isChecked())
        return d


class ContactsPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.contacts = []
        self.thumbs = ThumbCache(db)
        self.icons = ProfessionIcons(db.data_dir, self)
        self.icons.changed.connect(self.refresh)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(t("Ustalar ve Dükkanlar"))
        title.setObjectName("PageTitle")
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(t("🔍  İsim, meslek, yer ya da telefon numarası ile ara…"))
        self.search.setClearButtonEnabled(True)
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self._timer.start())
        self.kind = QComboBox()
        self.kind.addItem(t("Hepsi"), None)
        self.kind.addItem(t("🔧  Ustalar"), "usta")
        self.kind.addItem(t("🏪  Dükkanlar"), "dukkan")
        self.kind.currentIndexChanged.connect(lambda _: self.refresh())
        new_btn = QPushButton(t("＋  Yeni Usta / Dükkan"))
        new_btn.setObjectName("Primary")
        new_btn.clicked.connect(self.new_contact)
        header.addWidget(title)
        header.addSpacing(24)
        header.addWidget(self.search, 1)
        header.addWidget(self.kind)
        header.addSpacing(8)
        header.addWidget(new_btn)
        root.addLayout(header)

        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 12)
        self.table = QTableWidget(0, 8)
        labels = [""] + [t(x) for x in ("Tür", "İsim", "Meslek / alan", "Yer / adres", "Telefon", "İletişim", "Notlar")]
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setIconSize(QSize(46, 46))
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.horizontalHeader().setHighlightSections(False)
        setup_columns(self.table, db, "cols_contacts",
                      {0: 62, 1: 110, 2: 220, 3: 190, 4: 210, 5: 160, 6: 130, 7: 260})
        self.csort = db.get_setting("sort_contacts") or "name_asc"
        self.header_sort = HeaderSort(
            self.table, labels,
            {1: ("kind_asc", "kind_desc", False), 2: ("name_asc", "name_desc", False),
             3: ("prof_asc", "prof_desc", False), 4: ("place_asc", "place_desc", False),
             5: ("phone_asc", "phone_desc", False), 7: ("notes_asc", "notes_desc", False)},
            lambda: self.csort, self._set_sort)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        cl.addWidget(self.table, 1)
        self.empty = QLabel(alignment=Qt.AlignCenter)
        self.empty.setObjectName("Muted")
        self.empty.setStyleSheet("font-size: 13pt; padding: 40px;")
        cl.addWidget(self.empty)
        legend = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        legend.addWidget(self.summary)
        legend.addStretch()
        lg = QLabel(t("Renkli simge: bu yolla ulaşılabilir · Soluk simge: kullanılmıyor · "
                      "Simgeye tıklayınca WhatsApp / Telegram / arama açılır"))
        lg.setObjectName("Muted")
        legend.addWidget(lg)
        cl.addLayout(legend)
        root.addWidget(card, 1)

    def _set_sort(self, key):
        self.csort = key
        self.db.set_setting("sort_contacts", key)
        self.refresh()

    def refresh(self):
        cc = self.db.get_setting("country_code", "90")
        self.contacts = self.db.list_contacts(self.search.text(), self.kind.currentData(), self.csort)
        self.table.setRowCount(len(self.contacts))
        for row, c in enumerate(self.contacts):
            pic = QTableWidgetItem()
            if c["photo"]:
                pic.setIcon(self.thumbs.icon(c["photo"], 46))
                pic.setToolTip(t("{n} fotoğraf", n=c["photo_count"]) + " · " + t("büyütmek için çift tıklayın"))
            else:
                pic.setIcon(self.icons.icon(c["profession"], c["kind"], 46))
            kind = QTableWidgetItem(t("🏪  Dükkan") if c["kind"] == "dukkan" else t("🔧  Usta"))
            name = QTableWidgetItem(c["name"])
            name.setData(Qt.UserRole, c["id"])
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            prof = QTableWidgetItem(self.icons.icon(c["profession"], c["kind"], 28), c["profession"])
            cells = [pic, kind, name, prof, QTableWidgetItem(c["place"]),
                     QTableWidgetItem("\u2066" + c["phone"] + "\u2069"), QTableWidgetItem(""),
                     QTableWidgetItem(c["notes"].replace("\n", " "))]
            cells[7].setToolTip(c["notes"])
            for col, it in enumerate(cells):
                self.table.setItem(row, col, it)
            self.table.setCellWidget(row, 6, ChannelCell(c, cc))
        has = bool(self.contacts)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.empty.setText(t("Henüz usta ya da dükkan eklenmemiş.\n\n„＋ Yeni Usta / Dükkan“ ile ekleyin.")
                               if not self.search.text() and self.kind.currentData() is None
                               else t("Aramanıza uyan kayıt bulunamadı."))
        ustas = sum(1 for c in self.contacts if c["kind"] == "usta")
        self.summary.setText(t("{a} usta · {b} dükkan", a=ustas, b=len(self.contacts) - ustas))

    def _double_clicked(self, row, col):
        cid = self._row_id(row)
        if col == 0:
            c = self.db.get_contact(cid)
            if c and c["photos"]:
                PhotoViewer(self.db, c["photos"], 0, c["name"], self).exec()
                return
        if col != 6:
            self.edit_contact(cid)

    def _row_id(self, row):
        it = self.table.item(row, 2)
        return it.data(Qt.UserRole) if it else None

    def _selected_ids(self):
        return [self._row_id(r) for r in sorted({i.row() for i in self.table.selectedIndexes()})]

    def new_contact(self):
        dlg = ContactDialog(self.db, self.thumbs, self.icons, parent=self)
        if dlg.exec():
            self.db.save_contact(dlg.data(), photos=dlg.photo_entries())
            self.refresh()

    def edit_contact(self, cid):
        c = self.db.get_contact(cid) if cid else None
        if not c:
            return
        dlg = ContactDialog(self.db, self.thumbs, self.icons, c, self)
        if dlg.exec():
            self.db.save_contact(dlg.data(), cid, photos=dlg.photo_entries())
            self.refresh()

    def _context_menu(self, pos):
        ids = self._selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        if len(ids) == 1:
            c = self.db.get_contact(ids[0])
            menu.addAction(t("✎  Düzenle"), lambda: self.edit_contact(ids[0]))
            if c["phone"]:
                menu.addAction(t("Numarayı kopyala"),
                               lambda: QGuiApplication.clipboard().setText(c["phone"]))
            menu.addSeparator()
        menu.addAction(t("Sil"), lambda: self._delete(ids))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete(self, ids):
        text = (t("„{name}“ silinsin mi?", name=self.db.get_contact(ids[0])["name"]) if len(ids) == 1
                else t("Seçili {n} kayıt silinsin mi?", n=len(ids)))
        if confirm(self, t("Sil"), text, yes=t("Sil"), danger=True):
            self.db.delete_contacts(ids)
            self.refresh()
