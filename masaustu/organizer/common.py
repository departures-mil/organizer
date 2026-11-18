from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QLineEdit, QMessageBox, QVBoxLayout)

from .i18n import t


def photo_filter():
    return t("Resimler") + " (*.jpg *.jpeg *.png *.bmp *.gif *.webp *.heic *.tif *.tiff)"


PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic", ".tif", ".tiff"}


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


PRICES_HIDDEN = False   # sağ üstteki göz düğmesi: fiyatlar ekranda •••• olarak görünür


def fmt_price(price, currency):
    if price is None:
        return "—"
    if PRICES_HIDDEN:
        return "••••••"
    s = QLocale().toString(float(price), "f", 2)
    if currency == "USD":
        return f"${s}"
    if currency == "SYP":
        return f"{s} SYP"
    return f"{s} ₺"


def fmt_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y  %H:%M")
    except (TypeError, ValueError):
        return value or ""


def load_image(path, max_side=None) -> QImage:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # telefon fotoğraflarının yönünü düzeltir
    if max_side:
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > max_side:
            size.scale(max_side, max_side, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
    return reader.read()


def rounded(pix: QPixmap, side: int, radius: int = 10) -> QPixmap:
    """Fotoğrafı kare ve köşeleri yuvarlatılmış küçük resme çevirir."""
    from PySide6.QtGui import QPainter, QPainterPath
    out = QPixmap(side, side)
    out.fill(Qt.transparent)
    scaled = pix.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, side, side, radius, radius)
    p.setClipPath(path)
    p.drawPixmap((side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled)
    p.end()
    return out


class ThumbCache:
    """Fotoğrafların küçük hallerini diskte ve bellekte saklar."""

    def __init__(self, db, side=256):
        self.db = db
        self.side = side
        self._mem = {}

    def pixmap(self, fname):
        if not fname:
            return QPixmap()
        if fname in self._mem:
            return self._mem[fname]
        thumb_path = self.db.thumbs_dir / (Path(fname).stem + ".png")
        pix = QPixmap(str(thumb_path)) if thumb_path.exists() else QPixmap()
        if pix.isNull():
            img = load_image(self.db.photos_dir / fname, self.side)
            if not img.isNull():
                img.save(str(thumb_path))
                pix = QPixmap.fromImage(img)
        self._mem[fname] = pix
        return pix

    def icon(self, fname, side=48):
        pix = self.pixmap(fname)
        return QIcon(rounded(pix, side, 8)) if not pix.isNull() else QIcon()


def confirm(parent, title, text, yes=None, no=None, danger=False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    yes_btn = box.addButton(yes or t("Evet"), QMessageBox.AcceptRole)
    box.addButton(no or t("Vazgeç"), QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes_btn


def info(parent, title, text):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Information)
    box.addButton(t("Tamam"), QMessageBox.AcceptRole)
    box.exec()


class TreeCombo(QComboBox):
    """Yer ya da kategori ağacını tam yollarla gösteren seçim kutusu."""

    def __init__(self, db, table, none_text=None, parent=None):
        super().__init__(parent)
        self.db, self.table, self.none_text = db, table, none_text or t("— Seçilmedi —")
        self.setMinimumWidth(260)
        self.setMaxVisibleItems(18)
        self.reload()

    def reload(self, select=None):
        current = self.current_id() if select is None else select
        self.blockSignals(True)
        self.clear()
        self.addItem(self.none_text, None)
        for nid, name, depth, path in self.db.tree_ordered(self.table):
            self.addItem(("   " * depth) + (path if depth else name), nid)
            self.setItemData(self.count() - 1, path, Qt.ToolTipRole)
        self.set_current_id(current)
        self.blockSignals(False)

    def current_id(self):
        return self.currentData() if self.count() else None

    def set_current_id(self, nid):
        idx = self.findData(nid) if nid is not None else 0
        self.setCurrentIndex(max(idx, 0))


class NewNodeDialog(QDialog):
    """Yeni yer/kategori ekleme penceresi (üst öğe seçilebilir)."""

    def __init__(self, db, table, parent_id=None, parent=None):
        super().__init__(parent)
        loc = table == "locations"
        self.setWindowTitle(t("Yeni yer") if loc else t("Yeni kategori"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Örn. Balkon dolabı") if loc else t("Örn. Vidalar"))
        self.parent_combo = TreeCombo(db, table, none_text=t("— En üst seviye —"))
        self.parent_combo.set_current_id(parent_id)
        form.addRow(t("Ad:"), self.name)
        form.addRow(t("Üst yer:") if loc else t("Üst kategori:"), self.parent_combo)
        lay.addLayout(form)
        buttons = QDialogButtonBox()
        buttons.addButton(t("Ekle"), QDialogButtonBox.AcceptRole)
        buttons.addButton(t("Vazgeç"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _ok(self):
        if self.name.text().strip():
            self.accept()
        else:
            self.name.setFocus()

    def values(self):
        return self.name.text().strip(), self.parent_combo.current_id()


def icon_size(n):
    return QSize(n, n)


def setup_columns(table, db, key, widths, fixed=(0,)):
    """Excel gibi sütunlar: başlıktaki ayırıcıyı tutup sürükle, çift tıkla → içeriğe göre otomatik genişlik.
    Genişlikler ayarlarda saklanır (key), program yeniden açılınca geri gelir."""
    from PySide6.QtCore import QByteArray, QTimer
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView
    h = table.horizontalHeader()
    h.setSectionsMovable(False)
    h.setMinimumSectionSize(40)
    h.setSectionResizeMode(QHeaderView.Interactive)
    for col in fixed:
        h.setSectionResizeMode(col, QHeaderView.Fixed)
    h.setStretchLastSection(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    for col, w in widths.items():
        table.setColumnWidth(col, w)
    saved = db.get_setting(key)
    if saved:
        try:
            h.restoreState(QByteArray.fromBase64(saved.encode()))
            for col in fixed:
                h.setSectionResizeMode(col, QHeaderView.Fixed)
                table.setColumnWidth(col, widths.get(col, 62))
        except Exception:
            pass
    timer = QTimer(table, singleShot=True, interval=400)
    timer.timeout.connect(lambda: db.set_setting(key, bytes(h.saveState().toBase64()).decode()))
    h.sectionResized.connect(lambda *_: timer.start())

    def autosize(col):
        if col in fixed:
            return
        table.resizeColumnToContents(col)
    # QTableView çift tıklamayı zaten resizeColumnToContents'e bağlar; açıkça da bağlayalım
    try:
        h.sectionHandleDoubleClicked.disconnect()
    except Exception:
        pass
    h.sectionHandleDoubleClicked.connect(autosize)
    return h


def t_cols():
    from .i18n import t
    return t("Sütun genişliği: ayırıcı çizgiyi sürükleyin · çift tıklayınca otomatik ayarlanır")


class HeaderSort:
    """Sütun başlığına tıklayınca sıralama: ilk tıklama varsayılan yön, ikinci tıklama ters yön.
    cols: {sütun: (artan_anahtar, azalan_anahtar, önce_azalan)}; get()/put(anahtar) geçerli sıralamayı okur/yazar."""

    def __init__(self, table, labels, cols, get, put):
        self.table, self.labels, self.cols, self.get, self.put = table, labels, cols, get, put
        h = table.horizontalHeader()
        h.setSectionsClickable(True)
        h.setSortIndicatorShown(False)
        h.sectionClicked.connect(self._clicked)
        self.refresh()

    def _clicked(self, col):
        if col not in self.cols:
            return
        asc, desc, first_desc = self.cols[col]
        cur = self.get()
        if cur in (asc, desc):
            new = asc if cur == desc else desc
        else:
            new = desc if first_desc else asc
        self.put(new)
        self.refresh()

    def refresh(self):
        cur = self.get()
        texts = list(self.labels)
        for col, (asc, desc, _) in self.cols.items():
            if cur == asc:
                texts[col] += "  ▲"
            elif cur == desc:
                texts[col] += "  ▼"
        self.table.setHorizontalHeaderLabels(texts)
        tip = t("Sıralamak için tıklayın, yeniden tıklayınca ters sıralanır · Genişlik: ayırıcıyı sürükleyin, çift tıklayınca otomatik")
        for col in self.cols:
            it = self.table.horizontalHeaderItem(col)
            if it:
                it.setToolTip(tip)
