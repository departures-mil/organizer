from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .common import Card, ThumbCache, confirm, fmt_date, fmt_price, load_image, setup_columns, HeaderSort
from .db import Database, parse_voice
from . import extras, filtre
from .ek_arayuz import AskDialog, FilterDialog, HistoryDialog, fmt_day, saved_menu, status_text
from .extras import loan_text, overdue_days
from .i18n import t
from .item_dialog import ItemDialog, PhotoViewer
from .report import ReportDialog
from .shop import ShopLinks, has_shop, shop_title, shop_tooltip

AUTO_COLOR = "#8a969c"   # otomatik (tahmini) fiyatların rengi
LOW_COLOR = "#d97706"    # az kaldı (alışveriş listesinde)
LATE_COLOR = "#c0392b"   # ödünç dönüş günü geçti


def price_text(d):
    """Listede fiyat: otomatik girilmiş fiyat "⚡", kullanıcının girdiği "✎" işaretiyle."""
    if d["price"] is None:
        return "—"
    return ("⚡ " if d.get("price_auto") else "✎ ") + fmt_price(d["price"], d["currency"])


SORTS = [
    ("En yeni eklenen", "created_desc"),
    ("En eski eklenen", "created_asc"),
    ("Ada göre (A → Z)", "name_asc"),
    ("Ada göre (Z → A)", "name_desc"),
    ("Kategoriye göre (A → Z)", "category_asc"),
    ("Kategoriye göre (Z → A)", "category_desc"),
    ("Yere göre (A → Z)", "location_asc"),
    ("Yere göre (Z → A)", "location_desc"),
    ("Adet (çok → az)", "qty_desc"),
    ("Adet (az → çok)", "qty_asc"),
    ("Fiyat (yüksek → düşük)", "price_desc"),
    ("Fiyat (düşük → yüksek)", "price_asc"),
    ("Dükkan/Kişiye göre (A → Z)", "shop_asc"),
    ("Dükkan/Kişiye göre (Z → A)", "shop_desc"),
    ("Konuma göre (A → Z)", "place_asc"),
    ("Konuma göre (Z → A)", "place_desc"),
]
# sütun → (artan, azalan, ilk tıklamada azalan mı)
SORT_COLS = {1: ("name_asc", "name_desc", False), 2: ("qty_asc", "qty_desc", True),
             3: ("category_asc", "category_desc", False), 4: ("location_asc", "location_desc", False),
             5: ("price_asc", "price_desc", True), 6: ("created_asc", "created_desc", True),
             7: ("shop_asc", "shop_desc", False), 8: ("place_asc", "place_desc", False)}
UNASSIGNED = -1
ALL = None


class FilterTree(QTreeWidget):
    """Kategori ya da yer ağacı; seçilen düğüm ve alt düğümleri filtrelenir."""

    def __init__(self, db, table, parent=None):
        super().__init__(parent)
        self.db, self.table = db, table
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setAnimated(True)

    def reload(self):
        selected = self.selected_id()
        self.blockSignals(True)
        self.clear()
        counts = self.db.item_counts(self.table)
        rows = self.db.tree_rows(self.table)
        children = {}
        for r in rows:
            children.setdefault(r["parent_id"], []).append(r)

        def total(nid):
            return counts.get(nid, 0) + sum(total(c["id"]) for c in children.get(nid, []))

        bold = QFont()
        bold.setBold(True)
        all_item = QTreeWidgetItem([t("Tümü  ({n})", n=self.db.count_items())])
        all_item.setData(0, Qt.UserRole, ALL)
        all_item.setFont(0, bold)
        self.addTopLevelItem(all_item)
        by_id = {ALL: all_item}

        def build(parent_item, parent_id):
            for r in children.get(parent_id, []):
                n = total(r["id"])
                it = QTreeWidgetItem([f"{r['name']}  ({n})" if n else r["name"]])
                it.setData(0, Qt.UserRole, r["id"])
                if parent_item is None:
                    self.addTopLevelItem(it)
                else:
                    parent_item.addChild(it)
                by_id[r["id"]] = it
                build(it, r["id"])

        build(None, None)
        if counts.get(None):
            un = QTreeWidgetItem([t("Belirtilmemiş  ({n})", n=counts[None])])
            un.setData(0, Qt.UserRole, UNASSIGNED)
            un.setForeground(0, Qt.gray)
            self.addTopLevelItem(un)
            by_id[UNASSIGNED] = un
        self.expandAll()
        self.setCurrentItem(by_id.get(selected, all_item))
        self.blockSignals(False)

    def selected_id(self):
        it = self.currentItem()
        return it.data(0, Qt.UserRole) if it else ALL

    def filter_ids(self):
        nid = self.selected_id()
        if nid is ALL:
            return None
        if nid == UNASSIGNED:
            return {None}
        return self.db.descendants(self.table, nid)

    def select_all(self):
        self.setCurrentItem(self.topLevelItem(0))


class ItemDetail(Card):
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    quantity_changed = Signal(int, int)
    lend_requested = Signal(int)
    return_requested = Signal(int)
    buy_toggled = Signal(int, bool)

    def __init__(self, db, thumbs, parent=None):
        super().__init__(parent)
        self.db, self.thumbs = db, thumbs
        self.item = None
        self.current_photo = 0
        self.setMinimumWidth(290)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        self.photo = QLabel(t("Fotoğraf yok"), alignment=Qt.AlignCenter)
        self.photo.setObjectName("PhotoBox")
        self.photo.setFixedHeight(240)
        self.photo.setCursor(Qt.PointingHandCursor)
        self.photo.mousePressEvent = lambda e: self._open_viewer()
        outer.addWidget(self.photo)

        self.strip = QListWidget()
        self.strip.setViewMode(QListView.IconMode)
        self.strip.setFlow(QListView.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QSize(54, 54))
        self.strip.setFixedHeight(76)
        self.strip.setMovement(QListView.Static)
        self.strip.currentRowChanged.connect(self._show_photo)
        outer.addWidget(self.strip)

        self.name = QLabel()
        self.name.setObjectName("DetailName")
        self.name.setWordWrap(True)
        outer.addWidget(self.name)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)
        self.fields = {}
        for row, (key, label) in enumerate([("quantity", "Adet"), ("category", "Kategori"),
                                            ("location", "Yer"), ("price", "Fiyat"),
                                            ("created", "Eklenme"), ("shop", "Satın alındığı yer"),
                                            ("loan", "Ödünç"), ("receipts", "Fatura / fiş"),
                                            ("warranty", "Garanti bitişi"), ("expiry", "Son kullanma tarihi")]):
            l = QLabel(t(label))
            l.setObjectName("FieldName")
            v = QLabel()
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(l, row, 0, Qt.AlignTop)
            if key == "quantity":
                box = QHBoxLayout()
                minus = QPushButton("−")
                plus = QPushButton("+")
                for b, d in ((minus, -1), (plus, 1)):
                    b.setObjectName("Round")
                    b.setToolTip(t("Adedi azalt") if d < 0 else t("Adedi artır"))
                    b.clicked.connect(lambda _=False, d=d: self._qty(d))
                v.setStyleSheet("font-size: 13pt; font-weight: 700;")
                v.setMinimumWidth(48)
                v.setAlignment(Qt.AlignCenter)
                box.addWidget(minus)
                box.addWidget(v)
                box.addWidget(plus)
                box.addStretch()
                grid.addLayout(box, row, 1)
            elif key == "shop":
                box = QVBoxLayout()
                box.setSpacing(2)
                box.addWidget(v)
                self.shop_links = QHBoxLayout()
                self.shop_links.setContentsMargins(0, 0, 0, 0)
                box.addLayout(self.shop_links)
                grid.addLayout(box, row, 1)
            else:
                grid.addWidget(v, row, 1)
            self.fields[key] = v
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("Muted")
        self.notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.notes)
        outer.addStretch()

        extra = QHBoxLayout()
        self.lend_btn = QPushButton(t("🤝  Ödünç ver"))
        self.lend_btn.clicked.connect(self._lend_clicked)
        self.buy_btn = QPushButton(t("🛒  Listeye ekle"))
        self.buy_btn.setCheckable(True)
        self.buy_btn.setObjectName("Tool")
        self.buy_btn.setToolTip(t("Alışveriş listesine ekle / çıkar"))
        self.buy_btn.clicked.connect(lambda on: self.item and self.buy_toggled.emit(self.item["id"], on))
        extra.addWidget(self.lend_btn, 1)
        extra.addWidget(self.buy_btn, 1)
        outer.addLayout(extra)

        self.hist_btn = QPushButton(t("🕘  Değişiklik geçmişi"))
        self.hist_btn.setObjectName("Tool")
        self.hist_btn.clicked.connect(lambda: self.item and HistoryDialog(self.db, self.item["id"], self).exec())
        outer.addWidget(self.hist_btn)

        btns = QHBoxLayout()
        self.edit_btn = QPushButton(t("✎  Düzenle"))
        self.edit_btn.setObjectName("Primary")
        self.del_btn = QPushButton(t("Sil"))
        self.del_btn.setObjectName("Danger")
        self.edit_btn.clicked.connect(lambda: self.item and self.edit_requested.emit(self.item["id"]))
        self.del_btn.clicked.connect(lambda: self.item and self.delete_requested.emit(self.item["id"]))
        btns.addWidget(self.edit_btn, 1)
        btns.addWidget(self.del_btn)
        outer.addLayout(btns)
        self.show_item(None)

    def _qty(self, d):
        if self.item:
            self.quantity_changed.emit(self.item["id"], d)

    def _lend_clicked(self):
        if not self.item:
            return
        (self.return_requested if self.item.get("loan_to") else self.lend_requested).emit(self.item["id"])

    def show_item(self, item_id):
        self.item = self.db.get_item(item_id) if item_id else None
        has = self.item is not None
        for w in (self.edit_btn, self.del_btn, self.strip, self.lend_btn, self.buy_btn, self.hist_btn):
            w.setEnabled(has)
        self.strip.clear()
        if not has:
            self.photo.setPixmap(QPixmap())
            self.photo.setText(t("Ayrıntıları görmek için\nlistedeki bir eşyayı seçin"))
            self.name.setText("")
            for v in self.fields.values():
                v.setText("")
            self._show_shop(None)
            self.notes.setText("")
            self.strip.hide()
            return
        it = self.item
        self.name.setText(it["name"])
        self.fields["quantity"].setText(str(it["quantity"]))
        low = Database.is_low(it)
        self.fields["quantity"].setStyleSheet(f"font-size: 13pt; font-weight: 700; color: {LOW_COLOR};" if low
                                              else "font-size: 13pt; font-weight: 700;")
        self.fields["quantity"].setToolTip(t("⚠ Az kaldı (en az {n} olmalı) — alışveriş listesinde", n=it["min_qty"]) if low
                                           else t("En az adet: {n}", n=it["min_qty"]) if it["min_qty"] else "")
        self.fields["loan"].setText(loan_text(it) or "—")
        late = it.get("loan_to") and overdue_days(it) > 0
        self.fields["loan"].setStyleSheet(f"color: {LATE_COLOR}; font-weight: 700;" if late else "")
        self.fields["loan"].setToolTip(extras.history_text(it) and t("Geçmiş:") + "\n" + extras.history_text(it))
        self.lend_btn.setText(t("↩  Geri geldi") if it.get("loan_to") else t("🤝  Ödünç ver"))
        self.lend_btn.setObjectName("Primary" if it.get("loan_to") else "")
        self.lend_btn.style().unpolish(self.lend_btn)
        self.lend_btn.style().polish(self.lend_btn)
        self.buy_btn.setChecked(bool(it["to_buy"]) or low)
        self.buy_btn.setEnabled(not low)
        self.buy_btn.setText(t("🛒  Listede") if (it["to_buy"] or low) else t("🛒  Listeye ekle"))
        rc = len(it.get("receipts") or [])
        self.fields["receipts"].setText(t("🧾 {n} belge — görmek için tıklayın", n=rc) if rc else "—")
        self.fields["receipts"].setCursor(Qt.PointingHandCursor if rc else Qt.ArrowCursor)
        self.fields["receipts"].mousePressEvent = lambda e: rc and self._open_viewer(receipts=True)
        self.fields["category"].setText(it["category_path"] or "—")
        self.fields["location"].setText(it["location_path"] or "—")
        if it["price"] is not None and it.get("price_auto"):
            self.fields["price"].setText(fmt_price(it["price"], it["currency"]) + "   " +
                                         t("⚡ otomatik — kontrol edilmedi"))
            self.fields["price"].setStyleSheet(f"color: {AUTO_COLOR};")
        else:
            self.fields["price"].setText(price_text(it) if it["price"] is not None else "—")
            self.fields["price"].setStyleSheet("")
        self.fields["created"].setText(fmt_date(it["created_at"]))
        for key, field in (("warranty", "warranty_until"), ("expiry", "expires_on")):   # 2.3.0
            day = it.get(field) or ""
            st = filtre.day_status(day)
            self.fields[key].setText(f"{fmt_day(day)}   {status_text(day)}" if day else "—")
            self.fields[key].setStyleSheet("color: #c0392b; font-weight: 700;" if st == "over" else
                                           f"color: {LOW_COLOR}; font-weight: 700;" if st == "soon" else "")
        n_log = len(it.get("changelog") or [])
        self.hist_btn.setText(t("🕘  Değişiklik geçmişi ({n})", n=n_log) if n_log else t("🕘  Değişiklik geçmişi"))
        self.notes.setText(it["notes"])
        self._show_shop(it)
        for f in it["photos"]:
            li = QListWidgetItem(self.thumbs.icon(f, 54), "")
            self.strip.addItem(li)
        self.strip.setVisible(len(it["photos"]) > 1)
        if it["photos"]:
            self.strip.setCurrentRow(0)
            self._show_photo(0)
        else:
            self.photo.setPixmap(QPixmap())
            self.photo.setText(t("Fotoğraf yok\n(Düzenle ile ekleyebilirsiniz)"))

    def _show_shop(self, it):
        while self.shop_links.count():
            w = self.shop_links.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not it or not has_shop(it):
            self.fields["shop"].setText("—" if it else "")
            return
        lines = [x for x in (it.get("shop_name"), it.get("shop_place")) if x]
        if it.get("shop_phone"):
            lines.append("☎ " + it["shop_phone"])
        self.fields["shop"].setText("\n".join(lines))
        if it.get("shop_phone") and (it.get("shop_whatsapp") or it.get("shop_telegram")):
            self.shop_links.addWidget(ShopLinks(it, self.db.get_setting("country_code", "90"), show_text=False, icon=28))

    def _show_photo(self, row):
        if not self.item or row < 0 or row >= len(self.item["photos"]):
            return
        self.current_photo = row
        img = load_image(self.db.photos_dir / self.item["photos"][row], 900)
        pix = QPixmap.fromImage(img)
        if pix.isNull():
            self.photo.setText(t("Fotoğraf açılamadı"))
            return
        w = max(self.photo.width() - 8, 200)
        self.photo.setPixmap(pix.scaled(w, 232, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _open_viewer(self, receipts=False):
        files = (self.item or {}).get("receipts" if receipts else "photos") or []
        if self.item and files:
            v = PhotoViewer(self.db, files, 0 if receipts else self.current_photo,
                            self.item["name"] + (" — " + t("Fatura / fiş") if receipts else ""), self)
            v.resize(self.window().width() * 3 // 4, self.window().height() * 3 // 4)
            v.exec()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.item and self.item["photos"]:
            self._show_photo(self.current_photo)


class ItemsPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.thumbs = ThumbCache(db)
        self.items = []
        self.undo_stack = []   # [(açıklama, anlık görüntü)] — v.1.0.8 "Geri al"
        self.adv = {}          # 2.3.0 gelişmiş filtre

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(t("Eşyalarım"))
        title.setObjectName("PageTitle")
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(t("🔍  Eşya adı, kategori, yer ya da not ile ara…"))
        self.search.setClearButtonEnabled(True)
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self.reload_items)
        self.search.textChanged.connect(lambda: self._timer.start())
        self.sort = QComboBox()
        for label, key in SORTS:
            self.sort.addItem(t(label), key)
        saved = {"newest": "created_desc", "oldest": "created_asc", "category": "category_asc",
                 "location": "location_asc"}.get(db.get_setting("sort_items"), db.get_setting("sort_items"))
        self.sort.setCurrentIndex(max(0, self.sort.findData(saved)))
        self.sort.currentIndexChanged.connect(self._sort_changed)
        new_btn = QPushButton(t("＋  Yeni Eşya"))
        new_btn.setObjectName("Primary")
        new_btn.clicked.connect(self.new_item)
        sort_lbl = QLabel(t("Sırala:"))
        sort_lbl.setObjectName("Muted")
        header.addWidget(title)
        header.addSpacing(24)
        header.addWidget(self.search, 1)
        header.addSpacing(8)
        header.addWidget(sort_lbl)
        header.addWidget(self.sort)
        header.addSpacing(8)
        report_btn = QPushButton(t("🖨  Döküm"))
        report_btn.setToolTip(t("Seçili kategori ya da yerdeki bütün eşyaların listesi (yazdır / PDF)"))
        report_btn.clicked.connect(lambda: self.open_report())
        # 2.3.0: Döküm, „Dışa aktar ▾“ menüsünde (Ctrl+P de açar)
        # ---- 2.3.0: gelişmiş filtre · dışa aktar · Asistan
        self.filter_btn = QPushButton(t("⚙  Filtre ▾"))
        self.filter_btn.setToolTip(t("Fiyat aralığı, tarih, dükkan, garanti, durum… · kayıtlı filtreler"))
        self.filter_btn.clicked.connect(self._filter_menu)
        export_btn = QPushButton(t("⬇  Dışa aktar ▾"))
        export_btn.setToolTip(t("Listede görünen eşyaları Excel / CSV olarak kaydet ya da sigorta envanteri (PDF) hazırla"))
        export_btn.clicked.connect(lambda: self._export_menu(export_btn))
        ask_btn = QPushButton(t("✦  Asistan"))
        ask_btn.setToolTip(t("Eşyalarınız hakkında soru sorun: „Kışlık montlar nerede?“ (çevrim içi ve çevrim dışı)"))
        ask_btn.clicked.connect(lambda: AskDialog(self.db, self, self.search.text().strip() if "?" in self.search.text() else "").exec())
        header.addWidget(self.filter_btn)
        header.addWidget(export_btn)
        header.addWidget(ask_btn)
        header.addWidget(new_btn)
        root.addLayout(header)

        # ---- v.1.0.8 araç satırı: sesle ara, geri al, alışveriş listesi, ödünçtekiler, otomatik fiyatlar, çöp kutusu
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.mic_btn = QPushButton(t("🎤  Sesle ara / ekle"))
        self.mic_btn.setObjectName("Tool")
        self.mic_btn.setToolTip(t("Konuşarak arayın ya da ekleyin: „Matkap nerede?“ · „3 ampul ekle“\n"
                                  "Windows'un sesle yazma özelliği açılır (Win+H)."))
        self.mic_btn.clicked.connect(self._voice)
        self.undo_btn = QPushButton(t("↶  Geri al"))
        self.undo_btn.setObjectName("Tool")
        self.undo_btn.clicked.connect(self.undo)
        self.shop_btn = QPushButton()
        self.shop_btn.setObjectName("Tool")
        self.shop_btn.setToolTip(t("Adedi azalan ve listeye eklenen eşyalar"))
        self.shop_btn.clicked.connect(self.open_shopping)
        self.loan_btn = QPushButton()
        self.loan_btn.setObjectName("Tool")
        self.loan_btn.setCheckable(True)
        self.loan_btn.setToolTip(t("Yalnızca ödünç verilmiş eşyaları göster"))
        self.auto_btn = QPushButton()
        self.auto_btn.setObjectName("Tool")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setToolTip(t("Yalnızca otomatik girilmiş, henüz kontrol etmediğiniz fiyatları göster\n"
                                   "⚡ = otomatik fiyat · ✎ = sizin girdiğiniz fiyat"))
        self.loan_btn.toggled.connect(lambda on: (on and self.auto_btn.setChecked(False), self.reload_items()))
        self.auto_btn.toggled.connect(lambda on: (on and self.loan_btn.setChecked(False), self.reload_items()))
        self.trash_btn = QPushButton()
        self.trash_btn.setObjectName("Tool")
        self.trash_btn.setToolTip(t("Silinen eşyalar {n} gün burada kalır; geri yükleyebilirsiniz", n=extras.TRASH_DAYS))
        self.trash_btn.clicked.connect(self.open_trash)
        for b in (self.mic_btn, self.undo_btn):
            tools.addWidget(b)
        tools.addStretch()
        for b in (self.shop_btn, self.loan_btn, self.auto_btn, self.trash_btn):
            tools.addWidget(b)
        root.addLayout(tools)
        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.RichText)
        self.banner.linkActivated.connect(self._banner_link)
        self.banner.hide()
        root.addWidget(self.banner)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(14)

        fcard = Card()
        fl = QVBoxLayout(fcard)
        fl.setContentsMargins(14, 14, 14, 14)
        ft = QLabel(t("Sınıflandırma"))
        ft.setObjectName("SectionTitle")
        fl.addWidget(ft)
        self.tabs = QTabWidget()
        self.cat_tree = FilterTree(db, "categories")
        self.loc_tree = FilterTree(db, "locations")
        self.tabs.addTab(self.cat_tree, t("Kategoriler"))
        self.tabs.addTab(self.loc_tree, t("Yerler"))
        for tree in (self.cat_tree, self.loc_tree):
            tree.currentItemChanged.connect(lambda *_: self.reload_items())
            tree.setContextMenuPolicy(Qt.CustomContextMenu)
            tree.customContextMenuRequested.connect(lambda pos, tr=tree: self._tree_menu(tr, pos))
        fl.addWidget(self.tabs, 1)
        self.filter_info = QLabel()
        self.filter_info.setObjectName("Muted")
        self.filter_info.setWordWrap(True)
        fl.addWidget(self.filter_info)
        clear = QPushButton(t("Filtreleri temizle"))
        clear.clicked.connect(self.clear_filters)
        fl.addWidget(clear)
        splitter.addWidget(fcard)

        tcard = Card()
        tl = QVBoxLayout(tcard)
        tl.setContentsMargins(14, 10, 14, 12)
        self.table = QTableWidget(0, 9)
        labels = [""] + [t(x) for x in ("Adı", "Adet", "Kategori", "Yer", "Fiyat", "Eklenme", "Dükkan/Kişi", "Konum")]
        self.table.setHorizontalHeaderLabels(labels)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setIconSize(QSize(46, 46))
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setHighlightSections(False)
        setup_columns(self.table, db, "cols_items",
                      {0: 62, 1: 200, 2: 64, 3: 130, 4: 150, 5: 110, 6: 110, 7: 220, 8: 200},  # 2.2.1: dar tabloda Kategori de görünsün
                      order=[0, 1, 2, 3, 4, 5, 7, 8, 6])
        self.header_sort = HeaderSort(self.table, labels, SORT_COLS, self.sort.currentData,
                                      lambda k: self.sort.setCurrentIndex(self.sort.findData(k)))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_item(self._row_id(r)))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        tl.addWidget(self.table, 1)
        self.empty = QLabel(alignment=Qt.AlignCenter)
        self.empty.setObjectName("Muted")
        self.empty.setStyleSheet("font-size: 13pt; padding: 40px;")
        tl.addWidget(self.empty)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        tl.addWidget(self.summary)
        splitter.addWidget(tcard)

        self.detail = ItemDetail(db, self.thumbs)
        self.detail.edit_requested.connect(self.edit_item)
        self.detail.delete_requested.connect(lambda i: self.delete_items([i]))
        self.detail.quantity_changed.connect(self._change_qty)
        self.detail.lend_requested.connect(self.lend)
        self.detail.return_requested.connect(self.give_back)
        self.detail.buy_toggled.connect(lambda i, on: self._set_buy([i], on))
        splitter.addWidget(self.detail)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([240, 1000, 320])
        root.addWidget(splitter, 1)

    # ------------------------------------------------------------------ veri
    def _sort_changed(self, _=None):
        self.db.set_setting("sort_items", self.sort.currentData())
        self.header_sort.refresh()
        self.reload_items()

    def refresh(self):
        self.cat_tree.reload()
        self.loc_tree.reload()
        self.reload_items()

    def reload_items(self, keep_id=None):
        selected = keep_id if keep_id is not None else self._selected_ids()
        selected = {selected} if isinstance(selected, int) else set(selected)
        cat_ids, loc_ids = self.cat_tree.filter_ids(), self.loc_tree.filter_ids()
        self.items = self.db.list_items(self.search.text(), cat_ids, loc_ids, self.sort.currentData())
        if filtre.is_active(self.adv):
            self.items = filtre.apply(self.items, self.adv, days=self.warn_days())
        n_adv = filtre.count_active(self.adv)
        self.filter_btn.setText(t("⚙  Filtre ({n}) ▾", n=n_adv) if n_adv else t("⚙  Filtre ▾"))
        self.filter_btn.setObjectName("Primary" if n_adv else "")
        self.filter_btn.style().unpolish(self.filter_btn)
        self.filter_btn.style().polish(self.filter_btn)
        n_auto = sum(1 for d in self.items if d["price_auto"] and d["price"] is not None)
        self.auto_btn.setText(t("⚡ Kontrol edilmemiş fiyatlar ({n})", n=n_auto))
        if self.auto_btn.isChecked():
            self.items = [d for d in self.items if d["price_auto"] and d["price"] is not None]
        n_loan, n_late = self.db.loan_counts()
        self.loan_btn.setText(t("🤝 Ödünçtekiler ({n})", n=n_loan) + (t(" · ⚠ {n} gecikti", n=n_late) if n_late else ""))
        if self.loan_btn.isChecked():
            self.items = [d for d in self.items if d["loan_to"]]
        self.shop_btn.setText(t("🛒 Alışveriş listesi ({n})", n=len(self.db.shopping_list())))
        self.trash_btn.setText(t("🗑 Çöp kutusu ({n})", n=self.db.count_trash()))
        self._draw_undo()
        self._draw_banner()

        cc = self.db.get_setting("country_code", "90")
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.items))
        for row, d in enumerate(self.items):
            pic = QTableWidgetItem()
            if d["photo"]:
                pic.setIcon(self.thumbs.icon(d["photo"], 46))
                if d["photo_count"] > 1:
                    pic.setToolTip(t("{n} fotoğraf", n=d["photo_count"]))
            name = QTableWidgetItem(d["name"])
            name.setData(Qt.UserRole, d["id"])
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            if d["notes"]:
                name.setToolTip(d["notes"])
            wst = filtre.day_status(d.get("warranty_until"), days=self.warn_days())
            est = filtre.day_status(d.get("expires_on"), days=self.warn_days())
            if "over" in (wst, est) or "soon" in (wst, est):
                name.setText("⏳ " + d["name"])
                name.setForeground(QColor("#c0392b" if "over" in (wst, est) else LOW_COLOR))
                tips = [t("Garanti bitişi") + f": {fmt_day(d['warranty_until'])} · {status_text(d['warranty_until'])}"
                        if wst in ("soon", "over") else "",
                        t("Son kullanma tarihi") + f": {fmt_day(d['expires_on'])} · {status_text(d['expires_on'])}"
                        if est in ("soon", "over") else "", d["notes"]]
                name.setToolTip("\n".join(x for x in tips if x))
            if d["loan_to"]:
                name.setText("🤝 " + d["name"])
                name.setToolTip(loan_text(d) + ("\n" + d["notes"] if d["notes"] else ""))
                if d["loan_due"] and overdue_days(d) > 0:
                    name.setForeground(QColor(LATE_COLOR))
            qty = QTableWidgetItem(str(d["quantity"]))
            qty.setTextAlignment(Qt.AlignCenter)
            if d["quantity"] == 0:
                qty.setForeground(Qt.red)
                qty.setToolTip(t("Kalmadı"))
            elif Database.is_low(d):
                qty.setForeground(QColor(LOW_COLOR))
                qf = qty.font()
                qf.setBold(True)
                qty.setFont(qf)
                qty.setToolTip(t("⚠ Az kaldı (en az {n} olmalı) — alışveriş listesinde", n=d["min_qty"]))
            price = QTableWidgetItem(price_text(d))
            price.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if d["price"] is not None and d["price_auto"]:
                price.setForeground(QColor(AUTO_COLOR))
                pf = price.font()
                pf.setItalic(True)
                price.setFont(pf)
                price.setToolTip(t("⚡ Otomatik (tahmini) fiyat — henüz kontrol edilmedi.\n"
                                   "Düzenleyip fiyatı değiştirince ya da sağ tık → \"Fiyatı onayla\" deyince sizin fiyatınız olur."))
            elif d["price"] is not None:
                price.setToolTip(t("✎ Sizin girdiğiniz fiyat"))
            cat = QTableWidgetItem(d["category_path"].split(" › ")[-1] or "—")
            cat.setToolTip(d["category_path"])
            loc = QTableWidgetItem(d["location_path"].split(" › ")[-1] or "—")
            loc.setToolTip(d["location_path"])
            added = QTableWidgetItem(fmt_date(d["created_at"]).split()[0])
            added.setToolTip(fmt_date(d["created_at"]))
            shop = QTableWidgetItem()
            shop.setToolTip(shop_tooltip(d))
            place = QTableWidgetItem((d.get("shop_place") or "").strip() or "—")
            if (d.get("shop_place") or "").strip():
                place.setToolTip(d["shop_place"])
            cells = [pic, name, qty, cat, loc, price, added, shop, place]
            for col, c in enumerate(cells):
                self.table.setItem(row, col, c)
            if has_shop(d):
                self.table.setCellWidget(row, 7, ShopLinks(d, cc, icon=22, name_only=True))
            else:
                self.table.removeCellWidget(row, 7)
                shop.setText("—")
            if d["id"] in selected:
                self.table.selectRow(row)
        self.table.blockSignals(False)

        has = bool(self.items)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            if self.loan_btn.isChecked():
                self.empty.setText(t("Ödünç verilmiş eşya yok."))
            elif self.auto_btn.isChecked():
                self.empty.setText(t("Kontrol edilmemiş otomatik fiyat kalmadı. ✓"))
            elif self.db.count_items() == 0:
                self.empty.setText(t("Henüz eşya eklenmemiş.\n\n„＋ Yeni Eşya“ düğmesiyle ilk eşyanızı ekleyin."))
            else:
                self.empty.setText(t("Aramanıza uyan eşya bulunamadı."))

        totals = self.db.totals_by_currency(self.items)
        text = t("{n} eşya listeleniyor · toplam {q} adet", n=len(self.items), q=sum(d["quantity"] for d in self.items))
        if totals:
            text += t(" · Değer: ") + "  +  ".join(fmt_price(v, c) for c, v in totals.items())
        if n_auto:
            text += t(" · ⚡ {n} fiyat otomatik (kontrol edilmedi) · ✎ sizin girdiğiniz", n=n_auto)
        self.summary.setText(text)

        parts = []
        for tree, label in ((self.cat_tree, "Kategori"), (self.loc_tree, "Yer")):
            it = tree.currentItem()
            if it and tree.selected_id() is not ALL:
                parts.append(f"{t(label)}: {it.text(0).split('  (')[0]}")
        if n_adv:
            parts.append(t("Gelişmiş filtre: {n} koşul", n=n_adv))
        self.filter_info.setText(t("Etkin filtre — ") + ", ".join(parts) if parts else "")
        self._selection_changed()

    def _row_id(self, row):
        it = self.table.item(row, 1)
        return it.data(Qt.UserRole) if it else None

    def _selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._row_id(r) for r in rows]

    def _selection_changed(self):
        ids = self._selected_ids()
        self.detail.show_item(ids[0] if len(ids) == 1 else None)

    def open_report(self, table=None, node_id=ALL):
        if table is None:
            tree = self.cat_tree if self.tabs.currentIndex() == 0 else self.loc_tree
            table, node_id = tree.table, tree.selected_id()
        ReportDialog(self.db, table, node_id, self).exec()

    def _tree_menu(self, tree, pos):
        it = tree.itemAt(pos)
        if not it:
            return
        nid = it.data(0, Qt.UserRole)
        menu = QMenu(self)
        menu.addAction(t("🖨  Bu bölümün dökümünü al"), lambda: self.open_report(tree.table, nid))
        menu.exec(tree.viewport().mapToGlobal(pos))

    def clear_filters(self):
        self.adv = {}
        self.search.clear()
        self.cat_tree.select_all()
        self.loc_tree.select_all()

    # ------------------------------------------------------------------ işlemler
    def new_item(self):
        defaults = {}
        for tree, key in ((self.cat_tree, "category_id"), (self.loc_tree, "location_id")):
            nid = tree.selected_id()
            if nid not in (ALL, UNASSIGNED):
                defaults[key] = nid
        dlg = ItemDialog(self.db, self.thumbs, defaults=defaults, parent=self)
        if dlg.exec():
            new_id = self.db.save_item(dlg.data(), dlg.photo_entries())
            self.cat_tree.reload()
            self.loc_tree.reload()
            self.reload_items(keep_id=new_id)

    def edit_item(self, item_id):
        item = self.db.get_item(item_id) if item_id else None
        if not item:
            return
        dlg = ItemDialog(self.db, self.thumbs, item=item, parent=self)
        if dlg.exec():
            self._remember(t("„{name}“ düzenlendi", name=item["name"]), [item_id])
            self.db.save_item(dlg.data(), dlg.photo_entries(), item_id)
            self.cat_tree.reload()
            self.loc_tree.reload()
            self.reload_items(keep_id=item_id)

    def delete_items(self, ids):
        ids = [i for i in ids if i]
        if not ids:
            return
        if len(ids) == 1:
            text = t("„{name}“ çöp kutusuna taşınsın mı?", name=self.db.get_item(ids[0])["name"])
        else:
            text = t("Seçili {n} eşya çöp kutusuna taşınsın mı?", n=len(ids))
        text += "\n\n" + t("{n} gün içinde çöp kutusundan geri yükleyebilir ya da „↶ Geri al“ diyebilirsiniz.", n=extras.TRASH_DAYS)
        if confirm(self, t("Eşyayı sil"), text, yes=t("Sil"), danger=True):
            self._remember(t("{n} eşya silindi", n=len(ids)), ids)
            self.db.trash_items(ids)
            self.refresh()

    def _change_qty(self, item_id, delta):
        self._remember(t("Adet değişti"), [item_id], merge_key=("qty", item_id))
        self.db.change_quantity(item_id, delta)
        self.reload_items(keep_id=item_id)

    # ------------------------------------------------------------------ v.1.0.8
    def _remember(self, label, ids, merge_key=None):
        """Değişiklikten önceki hali saklar (Geri al). Aynı eşyada art arda adet değişimi tek adım sayılır."""
        if merge_key and self.undo_stack and self.undo_stack[-1][2] == merge_key:
            return
        self.undo_stack.append((label, self.db.snapshot(ids), merge_key))
        del self.undo_stack[:-30]

    def _draw_undo(self):
        self.undo_btn.setEnabled(bool(self.undo_stack))
        self.undo_btn.setToolTip(t("Son işlemi geri al (Ctrl+Z): {x}", x=self.undo_stack[-1][0]) if self.undo_stack
                                 else t("Geri alınacak işlem yok"))

    def undo(self):
        if not self.undo_stack:
            return
        label, snap, _ = self.undo_stack.pop()
        self.db.restore_snapshot(snap)
        self.refresh()
        self.reload_items(keep_id=[d["id"] for d in snap])
        self.summary.setText(t("↶ Geri alındı: {x}", x=label) + "   ·   " + self.summary.text())

    def lend(self, item_id):
        it = self.db.get_item(item_id)
        if not it:
            return
        dlg = extras.LoanDialog(it, self)
        if dlg.exec():
            self._remember(t("„{name}“ ödünç verildi", name=it["name"]), [item_id])
            self.db.lend_item(item_id, *dlg.values())
            self.reload_items(keep_id=item_id)

    def give_back(self, item_id):
        it = self.db.get_item(item_id)
        if it and confirm(self, t("↩  Geri geldi"), t("„{name}“ {who} kişisinden geri geldi mi?", name=it["name"], who=it["loan_to"]),
                          yes=t("↩  Geri geldi")):
            self._remember(t("„{name}“ geri geldi", name=it["name"]), [item_id])
            self.db.return_item(item_id)
            self.reload_items(keep_id=item_id)

    def _set_buy(self, ids, on):
        self._remember(t("Alışveriş listesi değişti"), ids)
        self.db.update_items_field(ids, "to_buy", int(bool(on)))
        self.reload_items(keep_id=ids)

    def open_shopping(self):
        dlg = extras.ShoppingDialog(self.db, self.thumbs, self)
        dlg.exec()
        if dlg.changed:
            self.reload_items()

    def open_trash(self):
        dlg = extras.TrashDialog(self.db, self.thumbs, self)
        dlg.exec()
        if dlg.changed:
            self.refresh()

    # ---- sesli / yazılı soru: "Matkap nerede?" · "3 ampul ekle"
    def _voice(self):
        if not extras.start_dictation(self.search):
            self.banner.setText(t("🎤 Arama kutusuna yazın ya da konuşun: „Matkap nerede?“ · „3 ampul ekle“. "
                                  "Sesle yazma Windows'ta Win+H ile açılır."))
            self.banner.show()

    def _draw_banner(self):
        text = self.search.text().strip()
        cmd = parse_voice(text) if text else None
        if not cmd or cmd["intent"] == "search" or not cmd["query"]:
            self.banner.hide()
            return
        q = cmd["query"]
        if cmd["intent"] == "add":
            n = f"{cmd['qty']} × " if cmd["qty"] else ""
            self.banner.setText(t("🎤 Yeni eşya: <b>{x}</b> — <a href='add'>＋ Ekle</a>", x=n + q))
        else:
            found = self.items[:3]
            if not found:
                self.banner.setText(t("🎤 „{x}“ bulunamadı.", x=q))
            else:
                parts = []
                for d in found:
                    where = d["location_path"] or t("yeri belirtilmemiş")
                    extra = " · " + loan_text(d) if d["loan_to"] else ""
                    parts.append(f"<b>{d['name']}</b> → 📍 {where}{extra}")
                more = len(self.items) - len(found)
                self.banner.setText("🎤 " + "<br>".join(parts) + (t("<br>… ve {n} eşya daha", n=more) if more > 0 else ""))
        self.banner.show()

    def _banner_link(self, link):
        cmd = parse_voice(self.search.text())
        if link == "add" and cmd["query"]:
            q = cmd["query"]
            defaults = {"name": q[:1].upper() + q[1:], "quantity": cmd["qty"] or 1}
            low = q.lower()
            for nid, name, depth, path in self.db.tree_ordered("locations"):
                if name.lower() in low and len(name) > 2:
                    defaults["location_id"] = nid
                    defaults["name"] = q.replace(name, "").strip() or q
            self.search.clear()
            dlg = ItemDialog(self.db, self.thumbs, defaults=defaults, parent=self)
            if dlg.exec():
                new_id = self.db.save_item(dlg.data(), dlg.photo_entries())
                self.refresh()
                self.reload_items(keep_id=new_id)

    def _context_menu(self, pos):
        ids = self._selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        if len(ids) == 1:
            menu.addAction(t("✎  Düzenle"), lambda: self.edit_item(ids[0]))
            menu.addAction(t("🕘  Değişiklik geçmişi"), lambda: HistoryDialog(self.db, ids[0], self).exec())
            menu.addSeparator()
        for table, field, label in (("categories", "category_id", "Kategoriye taşı"),
                                    ("locations", "location_id", "Yere taşı")):
            sub = menu.addMenu(t(label))
            sub.addAction(t("— Belirtilmemiş —"), lambda f=field: self._move(ids, f, None))
            for nid, name, depth, path in self.db.tree_ordered(table):
                sub.addAction(("    " * depth) + name, lambda f=field, n=nid: self._move(ids, f, n))
        menu.addSeparator()
        if len(ids) == 1:
            one = next((d for d in self.items if d["id"] == ids[0]), None)
            if one and one["loan_to"]:
                menu.addAction(t("↩  Geri geldi"), lambda: self.give_back(ids[0]))
            else:
                menu.addAction(t("🤝  Ödünç ver"), lambda: self.lend(ids[0]))
        menu.addAction(t("🛒  Alışveriş listesine ekle"), lambda: self._set_buy(ids, True))
        menu.addAction(t("Alışveriş listesinden çıkar"), lambda: self._set_buy(ids, False))
        priced = [d["id"] for d in self.items if d["id"] in ids and d["price"] is not None]
        if priced:
            menu.addSeparator()
            menu.addAction(t("✎  Fiyatı onayla (benim fiyatım)"), lambda: self._set_auto(priced, 0))
            menu.addAction(t("⚡  Otomatik fiyat olarak işaretle"), lambda: self._set_auto(priced, 1))
        menu.addSeparator()
        menu.addAction(t("🗑  Sil (çöp kutusuna)"), lambda: self.delete_items(ids))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _set_auto(self, ids, value):
        self._remember(t("Fiyat işareti değişti"), ids)
        self.db.update_items_field(ids, "price_auto", value)
        self.reload_items(keep_id=ids)

    def _move(self, ids, field, node_id):
        self._remember(t("{n} eşya taşındı", n=len(ids)), ids)
        self.db.update_items_field(ids, field, node_id)
        self.cat_tree.reload()
        self.loc_tree.reload()
        self.reload_items(keep_id=ids)

    # ------------------------------------------------------------------ 2.3.0
    def warn_days(self):
        try:
            return max(1, int(self.db.get_setting("warn_days", str(filtre.WARN_DAYS)) or filtre.WARN_DAYS))
        except ValueError:
            return filtre.WARN_DAYS

    def set_filter(self, f, reset_tree=True):
        """Panelden / kayıtlı filtreden gelen gelişmiş filtreyi uygular."""
        if reset_tree:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.cat_tree.select_all()
            self.loc_tree.select_all()
            self.loan_btn.setChecked(False)
            self.auto_btn.setChecked(False)
        self.adv = filtre.clean(f)
        self.reload_items()

    def _open_filter(self):
        dlg = FilterDialog(self.db, self.adv, self)
        if dlg.exec():
            self.adv = dlg.value()
            self.reload_items()

    def _filter_menu(self):
        m = saved_menu(self.db, self, lambda f: self.set_filter(f, reset_tree=False), self._open_filter)
        if filtre.is_active(self.adv):
            m.addSeparator()
            m.addAction(t("✕  Gelişmiş filtreyi kaldır"), lambda: self.set_filter({}, reset_tree=False))
        m.exec(self.filter_btn.mapToGlobal(self.filter_btn.rect().bottomLeft()))

    def _export_menu(self, btn):
        m = QMenu(self)
        m.addAction(t("📊  Excel dosyası (.xlsx)…"), lambda: self.export("xlsx"))
        m.addAction(t("📄  CSV dosyası (.csv)…"), lambda: self.export("csv"))
        m.addSeparator()
        m.addAction(t("🛡  Sigorta envanteri (fotoğraflı PDF / yazdır)…"), self.insurance)
        m.addAction(t("🖨  Döküm (kategori / yer)…"), lambda: self.open_report())
        m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def export(self, kind):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from . import disa_aktar, i18n
        from .common import info
        if not self.items:
            info(self, t("Dışa aktar"), t("Listede eşya yok."))
            return
        default = str(Path.home() / disa_aktar.default_name(kind))
        filt = "Excel (*.xlsx)" if kind == "xlsx" else "CSV (*.csv)"
        target, _ = QFileDialog.getSaveFileName(self, t("Dışa aktar"), default, filt)
        if not target:
            return
        head, rows, widths = disa_aktar.table(self.items, t)
        try:
            if kind == "xlsx":
                disa_aktar.write_xlsx(target, head, rows, widths, sheet=t("Eşyalarım"), rtl=i18n.is_rtl(),
                                      title=t("Organizer — {n} eşya", n=len(rows)))
            else:
                disa_aktar.write_csv(target, head, rows)
        except OSError as e:
            info(self, t("Dışa aktar"), str(e))
            return
        info(self, t("Dışa aktar"), t("{n} eşya kaydedildi:\n{path}", n=len(rows), path=target))

    def insurance(self):
        from .report import InsuranceDialog
        InsuranceDialog(self.db, list(self.items), self).exec()
