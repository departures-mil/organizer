from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .common import Card, ThumbCache, confirm, fmt_date, fmt_price, load_image, setup_columns, HeaderSort
from .i18n import t
from .item_dialog import ItemDialog, PhotoViewer
from .report import ReportDialog
from .shop import ShopLinks, has_shop, shop_title, shop_tooltip

AUTO_COLOR = "#8a969c"   # otomatik (tahmini) fiyatların rengi


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
                                            ("created", "Eklenme"), ("shop", "Satın alındığı yer")]):
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

    def show_item(self, item_id):
        self.item = self.db.get_item(item_id) if item_id else None
        has = self.item is not None
        for w in (self.edit_btn, self.del_btn, self.strip):
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

    def _open_viewer(self):
        if self.item and self.item["photos"]:
            v = PhotoViewer(self.db, self.item["photos"], self.current_photo, self.item["name"], self)
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
        header.addWidget(report_btn)
        self.auto_btn = QPushButton()
        self.auto_btn.setCheckable(True)
        self.auto_btn.setToolTip(t("Yalnızca otomatik girilmiş, henüz kontrol etmediğiniz fiyatları göster\n"
                                   "⚡ = otomatik fiyat · ✎ = sizin girdiğiniz fiyat"))
        self.auto_btn.toggled.connect(lambda _: self.reload_items())
        header.addWidget(self.auto_btn)
        header.addWidget(new_btn)
        root.addLayout(header)

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
                      {0: 62, 1: 320, 2: 70, 3: 150, 4: 150, 5: 110, 6: 110, 7: 220, 8: 200},
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
        n_auto = sum(1 for d in self.items if d["price_auto"] and d["price"] is not None)
        self.auto_btn.setText(t("⚡ Kontrol edilmemiş fiyatlar ({n})", n=n_auto))
        if self.auto_btn.isChecked():
            self.items = [d for d in self.items if d["price_auto"] and d["price"] is not None]

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
            qty = QTableWidgetItem(str(d["quantity"]))
            qty.setTextAlignment(Qt.AlignCenter)
            if d["quantity"] == 0:
                qty.setForeground(Qt.red)
                qty.setToolTip(t("Kalmadı"))
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
            if self.auto_btn.isChecked():
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
            self.db.save_item(dlg.data(), dlg.photo_entries(), item_id)
            self.cat_tree.reload()
            self.loc_tree.reload()
            self.reload_items(keep_id=item_id)

    def delete_items(self, ids):
        ids = [i for i in ids if i]
        if not ids:
            return
        if len(ids) == 1:
            text = t("„{name}“ silinsin mi? Fotoğrafları da silinecek.", name=self.db.get_item(ids[0])["name"])
        else:
            text = t("Seçili {n} eşya silinsin mi? Fotoğrafları da silinecek.", n=len(ids))
        if confirm(self, t("Eşyayı sil"), text, yes=t("Sil"), danger=True):
            self.db.delete_items(ids)
            self.refresh()

    def _change_qty(self, item_id, delta):
        self.db.change_quantity(item_id, delta)
        self.reload_items(keep_id=item_id)

    def _context_menu(self, pos):
        ids = self._selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        if len(ids) == 1:
            menu.addAction(t("✎  Düzenle"), lambda: self.edit_item(ids[0]))
            menu.addSeparator()
        for table, field, label in (("categories", "category_id", "Kategoriye taşı"),
                                    ("locations", "location_id", "Yere taşı")):
            sub = menu.addMenu(t(label))
            sub.addAction(t("— Belirtilmemiş —"), lambda f=field: self._move(ids, f, None))
            for nid, name, depth, path in self.db.tree_ordered(table):
                sub.addAction(("    " * depth) + name, lambda f=field, n=nid: self._move(ids, f, n))
        priced = [d["id"] for d in self.items if d["id"] in ids and d["price"] is not None]
        if priced:
            menu.addSeparator()
            menu.addAction(t("✎  Fiyatı onayla (benim fiyatım)"), lambda: self._set_auto(priced, 0))
            menu.addAction(t("⚡  Otomatik fiyat olarak işaretle"), lambda: self._set_auto(priced, 1))
        menu.addSeparator()
        menu.addAction(t("Sil"), lambda: self.delete_items(ids))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _set_auto(self, ids, value):
        self.db.update_items_field(ids, "price_auto", value)
        self.reload_items(keep_id=ids)

    def _move(self, ids, field, node_id):
        self.db.update_items_field(ids, field, node_id)
        self.cat_tree.reload()
        self.loc_tree.reload()
        self.reload_items(keep_id=ids)
