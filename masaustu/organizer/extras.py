"""v.1.0.8 eklentileri: çöp kutusu, alışveriş listesi, ödünç, usta iş geçmişi, sesli arama, admin ile iletişim."""
import sys
import urllib.parse
from datetime import date, datetime

from PySide6.QtCore import QDate, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import goster
from .common import confirm, fmt_date, fmt_price, info
from .db import CURRENCIES, TRASH_DAYS, today_str
from .i18n import t

# Yöneticinin adresi programda görünmez; mesaj FormSubmit üzerinden doğrudan iletilir.
_ADMIN_B64 = ""


def admin_email():
    import base64
    return base64.b64decode(_ADMIN_B64).decode()[::-1]


def fmt_day(v):
    """"2026-11-21" → "21.11.2026" """
    try:
        return datetime.strptime(v, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return v or ""


def loan_text(d):
    """"🤝 Ahmet · 20.11.2026 → 25.11.2026 (2 gün gecikti)" """
    if not d.get("loan_to"):
        return ""
    s = "🤝 " + d["loan_to"]
    if d.get("loan_date"):
        s += " · " + fmt_day(d["loan_date"])
    if d.get("loan_due"):
        s += " → " + fmt_day(d["loan_due"])
        late = overdue_days(d)
        if late > 0:
            s += "  " + t("({n} gün gecikti)", n=late)
    return s


def overdue_days(d):
    try:
        due = datetime.strptime(d.get("loan_due") or "", "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (date.today() - due).days


def _table(cols):
    tb = QTableWidget(0, len(cols))
    tb.setHorizontalHeaderLabels([t(c) for c in cols])
    tb.verticalHeader().hide()
    tb.setShowGrid(False)
    tb.setAlternatingRowColors(True)
    tb.setSelectionBehavior(QAbstractItemView.SelectRows)
    tb.setSelectionMode(QAbstractItemView.ExtendedSelection)
    tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tb.verticalHeader().setDefaultSectionSize(48)
    tb.setIconSize(QSize(40, 40))
    tb.horizontalHeader().setHighlightSections(False)
    return tb


def _date_edit(value=""):
    e = QDateEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd.MM.yyyy")
    e.setLayoutDirection(Qt.LeftToRight)
    d = QDate.fromString(value or "", "yyyy-MM-dd")
    e.setDate(d if d.isValid() else QDate.currentDate())
    return e


# ====================================================================== ödünç
class LoanDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("🤝  Ödünç ver"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        title = QLabel(t("„{name}“ kime ödünç verildi?", name=item["name"]))
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        lay.addWidget(title)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.to = QLineEdit(item.get("loan_to") or "")
        self.to.setPlaceholderText(t("Örn. Komşu Ahmet"))
        form.addRow(t("Kime:"), self.to)
        self.phone = QLineEdit(item.get("loan_phone") or "")
        self.phone.setLayoutDirection(Qt.LeftToRight)
        self.phone.setPlaceholderText(t("(isteğe bağlı)"))
        form.addRow(t("Telefonu:"), self.phone)
        self.date = _date_edit(item.get("loan_date") or today_str())
        form.addRow(t("Verildiği gün:"), self.date)
        due_row = QHBoxLayout()
        self.has_due = QCheckBox(t("Geri getireceği gün:"))
        self.due = _date_edit(item.get("loan_due") or QDate.currentDate().addDays(7).toString("yyyy-MM-dd"))
        self.has_due.setChecked(bool(item.get("loan_due")) or not item.get("loan_to"))
        self.due.setEnabled(self.has_due.isChecked())
        self.has_due.toggled.connect(self.due.setEnabled)
        due_row.addWidget(self.has_due)
        due_row.addWidget(self.due)
        due_row.addStretch()
        form.addRow("", due_row)
        lay.addLayout(form)
        hint = QLabel(t("Dönüş günü geçince eşya listede kırmızı görünür. Geri gelince „↩ Geri geldi“ deyin; kayıt geçmişte kalır."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QDialogButtonBox()
        ok = bb.addButton(t("Kaydet"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(t("Vazgeç"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.to.setFocus()

    def _ok(self):
        if not self.to.text().strip():
            self.to.setFocus()
            return
        self.accept()

    def values(self):
        return (self.to.text().strip(), self.phone.text().strip(), self.date.date().toString("yyyy-MM-dd"),
                self.due.date().toString("yyyy-MM-dd") if self.has_due.isChecked() else "")


def history_text(d):
    rows = []
    for h in reversed(d.get("loan_history") or []):
        rows.append(f"• {h.get('to', '')}: {fmt_day(h.get('date'))} → {fmt_day(h.get('returned'))}")
    return "\n".join(rows[:10])


# ====================================================================== çöp kutusu
class TrashDialog(QDialog):
    """Silinen eşyalar: geri yükle ya da kalıcı sil. 30 günü dolanlar kendiliğinden silinir."""

    def __init__(self, db, thumbs, parent=None):
        super().__init__(parent)
        self.db, self.thumbs = db, thumbs
        self.changed = False
        self.setWindowTitle(t("🗑  Çöp kutusu"))
        self.setMinimumSize(820, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        title = QLabel(t("🗑  Çöp kutusu"))
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        hint = QLabel(t("Silinen eşyalar fotoğraflarıyla birlikte {n} gün burada kalır, sonra kendiliğinden kalıcı olarak silinir.",
                        n=TRASH_DAYS))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.table = _table(["", "Adı", "Adet", "Yer", "Silindiği gün", "Kalan"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((0, 52), (2, 60), (3, 180), (4, 130), (5, 90)):
            self.table.setColumnWidth(c, w)
        lay.addWidget(self.table, 1)
        self.empty = QLabel(t("Çöp kutusu boş."), alignment=Qt.AlignCenter)
        self.empty.setObjectName("Muted")
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        self.restore_btn = QPushButton(t("↩  Geri yükle"))
        self.restore_btn.setObjectName("Primary")
        self.restore_btn.clicked.connect(self._restore)
        self.purge_btn = QPushButton(t("Kalıcı olarak sil"))
        self.purge_btn.setObjectName("Danger")
        self.purge_btn.clicked.connect(self._purge)
        self.empty_btn = QPushButton(t("Çöp kutusunu boşalt"))
        self.empty_btn.setObjectName("Danger")
        self.empty_btn.clicked.connect(self._empty)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.accept)
        row.addWidget(self.restore_btn)
        row.addWidget(self.purge_btn)
        row.addStretch()
        row.addWidget(self.empty_btn)
        row.addWidget(close)
        lay.addLayout(row)
        self.table.cellDoubleClicked.connect(lambda *_: self._restore())
        self.reload()

    def reload(self):
        self.items = self.db.list_items(sort="trashed_desc", trashed=True)
        self.table.setRowCount(len(self.items))
        now = datetime.utcnow()
        for r, d in enumerate(self.items):
            pic = QTableWidgetItem()
            if d["photo"]:
                pic.setIcon(self.thumbs.icon(d["photo"], 40))
            name = QTableWidgetItem(d["name"])
            name.setData(Qt.UserRole, d["id"])
            try:
                when = datetime.strptime(d["trashed_at"][:19], "%Y-%m-%dT%H:%M:%S")
                left = max(0, TRASH_DAYS - (now - when).days)
                when_s = when.strftime("%d.%m.%Y")
            except ValueError:
                left, when_s = TRASH_DAYS, ""
            cells = [pic, name, QTableWidgetItem(str(d["quantity"])), QTableWidgetItem(d["location_path"] or "—"),
                     QTableWidgetItem(when_s), QTableWidgetItem(t("{n} gün", n=left))]
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        has = bool(self.items)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        for b in (self.restore_btn, self.purge_btn, self.empty_btn):
            b.setEnabled(has)

    def _ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 1).data(Qt.UserRole) for r in rows]

    def _restore(self):
        ids = self._ids()
        if ids:
            self.db.restore_items(ids)
            self.changed = True
            self.reload()

    def _purge(self):
        ids = self._ids()
        if ids and confirm(self, t("Kalıcı olarak sil"),
                           t("Seçili {n} eşya kalıcı olarak silinsin mi? Bu işlem geri alınamaz.", n=len(ids)),
                           yes=t("Kalıcı olarak sil"), danger=True):
            self.db.purge_items(ids)
            self.changed = True
            self.reload()

    def _empty(self):
        ids = [d["id"] for d in self.items]
        if ids and confirm(self, t("Çöp kutusunu boşalt"),
                           t("Çöp kutusundaki {n} eşya kalıcı olarak silinsin mi? Bu işlem geri alınamaz.", n=len(ids)),
                           yes=t("Çöp kutusunu boşalt"), danger=True):
            self.db.purge_items(ids)
            self.changed = True
            self.reload()


# ====================================================================== alışveriş listesi
def shopping_text(db, items):
    lines = [t("🛒 Alışveriş listesi") + f" — {date.today():%d.%m.%Y}", ""]
    for d in items:
        need = max(1, int(d["min_qty"] or 0) - int(d["quantity"] or 0)) if db.is_low(d) else 1
        s = f"☐ {d['name']} × {need}"
        if d.get("shop_name"):
            s += f"  ({d['shop_name']})"
        lines.append(s)
    return "\n".join(lines)


class ShoppingDialog(QDialog):
    """Adedi „en az“ sınırının altına düşen eşyalar + elle eklenenler."""

    def __init__(self, db, thumbs, parent=None):
        super().__init__(parent)
        self.db, self.thumbs = db, thumbs
        self.changed = False
        self.setWindowTitle(t("🛒  Alışveriş listesi"))
        self.setMinimumSize(900, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        title = QLabel(t("🛒  Alışveriş listesi"))
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        hint = QLabel(t("Eşyanın „En az adet“ değeri girildiyse adedi bunun altına düşünce kendiliğinden buraya gelir. "
                        "Başka eşyaları da elle ekleyebilirsiniz. Aldıktan sonra „✓ Alındı“ deyin; adet artar."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.table = _table(["", "Adı", "Var", "En az", "Alınacak", "Neden", "Dükkan/Kişi"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((0, 52), (2, 60), (3, 60), (4, 80), (5, 150), (6, 200)):
            self.table.setColumnWidth(c, w)
        lay.addWidget(self.table, 1)
        self.empty = QLabel(t("Alışveriş listesi boş. ✓"), alignment=Qt.AlignCenter)
        self.empty.setObjectName("Muted")
        self.empty.setStyleSheet("font-size: 13pt; padding: 30px;")
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        self.got_btn = QPushButton(t("✓  Alındı"))
        self.got_btn.setObjectName("Primary")
        self.got_btn.clicked.connect(self._bought)
        self.rm_btn = QPushButton(t("Listeden çıkar"))
        self.rm_btn.clicked.connect(self._remove)
        add = QPushButton(t("＋  Listeye eşya ekle"))
        add.clicked.connect(self._add)
        copy = QPushButton(t("📋  Kopyala"))
        copy.setToolTip(t("Listeyi metin olarak kopyalar (WhatsApp'a yapıştırabilirsiniz)"))
        copy.clicked.connect(self._copy)
        wa = QPushButton(t("WhatsApp ile gönder"))
        wa.clicked.connect(self._whatsapp)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.accept)
        for b in (self.got_btn, self.rm_btn, add):
            row.addWidget(b)
        row.addStretch()
        for b in (copy, wa, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.reload()

    def reload(self):
        self.items = self.db.shopping_list()
        self.table.setRowCount(len(self.items))
        for r, d in enumerate(self.items):
            low = self.db.is_low(d)
            pic = QTableWidgetItem()
            if d["photo"]:
                pic.setIcon(self.thumbs.icon(d["photo"], 40))
            name = QTableWidgetItem(d["name"])
            name.setData(Qt.UserRole, d["id"])
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            need = max(1, int(d["min_qty"]) - int(d["quantity"])) if low else 1
            why = t("⚠ Az kaldı") if low else t("Elle eklendi")
            cells = [pic, name, QTableWidgetItem(str(d["quantity"])),
                     QTableWidgetItem(str(d["min_qty"]) if d["min_qty"] else "—"), QTableWidgetItem(str(need)),
                     QTableWidgetItem(why), QTableWidgetItem(d.get("shop_name") or "—")]
            for c in (2, 3, 4):
                cells[c].setTextAlignment(Qt.AlignCenter)
            if low:
                cells[5].setForeground(Qt.darkYellow)
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        has = bool(self.items)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.got_btn.setEnabled(has)
        self.rm_btn.setEnabled(has)

    def _sel(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows]

    def _bought(self):
        for d in self._sel():
            need = max(1, int(d["min_qty"]) - int(d["quantity"])) if self.db.is_low(d) else 1
            n, ok = QInputDialog.getInt(self, t("✓  Alındı"), t("„{name}“ kaç adet alındı?", name=d["name"]), need, 0, 1_000_000)
            if not ok:
                return
            self.db.bought(d["id"], n)
            self.changed = True
        self.reload()

    def _remove(self):
        for d in self._sel():
            if d["to_buy"]:
                self.db.update_items_field([d["id"]], "to_buy", 0)
            if self.db.is_low(d) and confirm(self, t("Listeden çıkar"),
                                             t("„{name}“ için az kaldı uyarısı kapatılsın mı? (En az adet: {n})",
                                               name=d["name"], n=d["min_qty"]), yes=t("Uyarıyı kapat")):
                self.db.update_items_field([d["id"]], "min_qty", 0)
            self.changed = True
        self.reload()

    def _add(self):
        names = {f"{d['name']}  ·  {d['location_path'] or '—'}": d["id"] for d in self.db.list_items(sort="name_asc")
                 if not d["to_buy"]}
        if not names:
            return
        key, ok = QInputDialog.getItem(self, t("＋  Listeye eşya ekle"), t("Eşya:"), sorted(names, key=str.lower), 0, True)
        if ok and key in names:
            self.db.update_items_field([names[key]], "to_buy", 1)
            self.changed = True
            self.reload()

    def _copy(self):
        QGuiApplication.clipboard().setText(shopping_text(self.db, self.items))
        info(self, t("📋  Kopyala"), t("Liste kopyalandı."))

    def _whatsapp(self):
        QDesktopServices.openUrl(QUrl("https://wa.me/?text=" + urllib.parse.quote(shopping_text(self.db, self.items))))


# ====================================================================== usta iş geçmişi
class JobDialog(QDialog):
    def __init__(self, job=None, currency="USD", parent=None):
        super().__init__(parent)
        job = job or {}
        self.setWindowTitle(t("İşi düzenle") if job else t("Yeni iş / ödeme"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.date = _date_edit(job.get("date") or today_str())
        form.addRow(t("Tarih:"), self.date)
        self.work = QLineEdit(job.get("work") or "")
        self.work.setPlaceholderText(t("Örn. Mutfak musluğu değişti"))
        form.addRow(t("Yapılan iş:"), self.work)
        prow = QHBoxLayout()
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1e12)
        self.cost.setDecimals(2)
        self.cost.setGroupSeparatorShown(True)
        self.cost.setMinimumWidth(160)
        self.cost.setValue(float(job.get("cost") or 0))
        self.cur = QComboBox()
        for code, sym, name in CURRENCIES:
            self.cur.addItem(f"{sym}  {t(name)}", code)
        self.cur.setCurrentIndex(max(0, self.cur.findData(job.get("currency") or currency)))
        prow.addWidget(self.cost)
        prow.addWidget(self.cur)
        prow.addStretch()
        form.addRow(t("Ödenen ücret:"), prow)
        self.notes = QPlainTextEdit(job.get("notes") or "")
        self.notes.setFixedHeight(70)
        form.addRow(t("Notlar:"), self.notes)
        lay.addLayout(form)
        bb = QDialogButtonBox()
        ok = bb.addButton(t("Kaydet"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(t("Vazgeç"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.job_id = job.get("id")
        self.work.setFocus()

    def _ok(self):
        if not self.work.text().strip():
            self.work.setFocus()
            return
        self.accept()

    def value(self):
        import uuid
        c = self.cost.value()
        return {"id": self.job_id or uuid.uuid4().hex[:12], "date": self.date.date().toString("yyyy-MM-dd"),
                "work": self.work.text().strip(), "cost": c if c > 0 else None, "currency": self.cur.currentData(),
                "notes": self.notes.toPlainText().strip()}


def jobs_summary(jobs):
    from .db import Database
    tot = Database.jobs_total(jobs)
    if not jobs:
        return ""
    s = t("{n} iş", n=len(jobs))
    if tot:
        s += " · " + "  +  ".join(fmt_price(v, c) for c, v in tot.items())
    return s


class JobsEditor(QWidget):
    """Usta / dükkan formunda: yapılan işler ve ödenen ücretler."""

    def __init__(self, jobs=None, currency="USD", parent=None):
        super().__init__(parent)
        self.jobs = sorted([dict(j) for j in (jobs or [])], key=lambda j: j.get("date") or "", reverse=True)
        self.currency = currency
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(t("🧾  Yapılan işler ve ödemeler"))
        lbl.setObjectName("SectionTitle")
        self.total = QLabel()
        self.total.setObjectName("Muted")
        add = QPushButton(t("＋ İş ekle"))
        add.clicked.connect(self._add)
        edit = QPushButton(t("✎ Düzenle"))
        edit.clicked.connect(self._edit)
        rm = QPushButton(t("Sil"))
        rm.setObjectName("Danger")
        rm.clicked.connect(self._remove)
        head.addWidget(lbl)
        head.addSpacing(10)
        head.addWidget(self.total, 1)
        head.addWidget(add)
        head.addWidget(edit)
        head.addWidget(rm)
        lay.addLayout(head)
        self.table = _table(["Tarih", "Yapılan iş", "Ücret", "Notlar"])
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 160)
        self.table.setMinimumHeight(150)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        lay.addWidget(self.table, 1)
        self._draw()

    def _draw(self):
        self.table.setRowCount(len(self.jobs))
        for r, j in enumerate(self.jobs):
            cells = [QTableWidgetItem(fmt_day(j.get("date"))), QTableWidgetItem(j.get("work") or ""),
                     QTableWidgetItem(fmt_price(j.get("cost"), j.get("currency")) if j.get("cost") is not None else "—"),
                     QTableWidgetItem((j.get("notes") or "").replace("\n", " "))]
            cells[2].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        self.total.setText(jobs_summary(self.jobs) or t("Henüz iş kaydı yok"))

    def _row(self):
        r = self.table.currentRow()
        return r if 0 <= r < len(self.jobs) else None

    def _add(self):
        dlg = JobDialog(currency=self.currency, parent=self)
        if dlg.exec():
            self.jobs.insert(0, dlg.value())
            self.jobs.sort(key=lambda j: j.get("date") or "", reverse=True)
            self._draw()

    def _edit(self):
        r = self._row()
        if r is None:
            return
        dlg = JobDialog(self.jobs[r], self.currency, self)
        if dlg.exec():
            self.jobs[r] = dlg.value()
            self.jobs.sort(key=lambda j: j.get("date") or "", reverse=True)
            self._draw()

    def _remove(self):
        r = self._row()
        if r is not None and confirm(self, t("Sil"), t("Bu iş kaydı silinsin mi?"), yes=t("Sil"), danger=True):
            self.jobs.pop(r)
            self._draw()

    def value(self):
        return self.jobs


# ====================================================================== sesli arama
def start_dictation(widget):
    """Windows'un sesle yazma özelliğini (Win+H) açar; söylenen yazı arama kutusuna yazılır.
    Türkçe, İngilizce ve Arapça desteklenir (Windows 10/11, internet gerekir)."""
    widget.setFocus()
    widget.selectAll()
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN, VK_H, UP = 0x5B, 0x48, 0x0002

        def press():
            user32.keybd_event(VK_LWIN, 0, 0, 0)
            user32.keybd_event(VK_H, 0, 0, 0)
            user32.keybd_event(VK_H, 0, UP, 0)
            user32.keybd_event(VK_LWIN, 0, UP, 0)
        QTimer.singleShot(150, press)
        return True
    except Exception:
        return False


# ====================================================================== admin ile iletişim
class FeedbackDialog(QDialog):
    """Programı kullananlar geliştiriciye öneri / hata bildirimi gönderir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("✉  Admin ile iletişime geç"))
        self.setMinimumSize(560, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        title = QLabel(t("✉  Admin ile iletişime geç"))
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        hint = QLabel(t("Öneri, istek ya da hata bildirimlerinizi yazın. Programın geliştirilmesi için doğrudan geliştiriciye gider."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.kind = QComboBox()
        for k in ("💡 Öneri / istek", "🐞 Hata bildirimi", "❓ Soru", "💬 Diğer"):
            self.kind.addItem(t(k))
        form.addRow(t("Konu:"), self.kind)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("(isteğe bağlı) adınız, telefonunuz ya da e-postanız"))
        form.addRow(t("Size ulaşma:"), self.name)
        lay.addLayout(form)
        self.msg = QPlainTextEdit()
        self.msg.setPlaceholderText(t("Mesajınız…"))
        lay.addWidget(self.msg, 1)
        row = QHBoxLayout()
        self.send_btn = QPushButton(t("✉  Gönder"))
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._send)
        mail = QPushButton(t("✉  E-posta uygulamasıyla gönder"))
        mail.clicked.connect(self._mail)
        gmail = QPushButton(t("Gmail ile gönder (tarayıcı)"))
        gmail.clicked.connect(self._gmail)
        copy = QPushButton(t("📋  Kopyala"))
        copy.clicked.connect(self._copy)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.reject)
        row.addWidget(self.send_btn)
        row.addWidget(mail)
        row.addWidget(gmail)
        row.addWidget(copy)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)

    def _subject(self):
        return f"Organizer {goster()} — {self.kind.currentText()}"

    def _body(self):
        import platform
        parts = [self.msg.toPlainText().strip(), "", "—"]
        if self.name.text().strip():
            parts.append(t("Size ulaşma:") + " " + self.name.text().strip())
        parts.append(f"Organizer {goster()} · {t('Masaüstü')} · {platform.system()} {platform.release()}")
        return "\n".join(parts)

    def _ready(self):
        if not self.msg.toPlainText().strip():
            self.msg.setFocus()
            return False
        return True

    def _send(self):
        """Doğrudan gönderim (FormSubmit). Gönderilemezse mesaj kaybolmaz: giden kutusuna yazılır ve
        bağlantı kurulunca (ya da yönetici formu etkinleştirince) program kendiliğinden yeniden gönderir."""
        import re
        import threading
        from PySide6.QtWidgets import QApplication
        from . import i18n
        if not self._ready():
            return
        contact = self.name.text().strip()
        body = {"_subject": "Organizer: " + self.kind.currentText(), "_template": "table", "_captcha": "false",
                "Konu": self.kind.currentText(), "Ulasma": contact or "-", "Mesaj": self.msg.toPlainText().strip()[:5000],
                "Surum": goster(), "Cihaz": "Windows", "Dil": i18n.LANG,
                "Tarih": datetime.now().strftime("%d.%m.%Y %H:%M")}
        m = re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact)
        if m:
            body["email"] = body["_replyto"] = m.group(0)
        self.send_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        res = {}
        th = threading.Thread(target=lambda: res.update(r=feedback_post(body)), daemon=True)
        th.start()
        while th.is_alive():                      # arayüz donmasın
            QApplication.processEvents()
            th.join(0.05)
        QApplication.restoreOverrideCursor()
        self.send_btn.setEnabled(True)
        if res.get("r") == "ok":
            self.msg.clear()
            info(self, t("✉  Admin ile iletişime geç"), t("Mesajınız yöneticiye iletildi. Teşekkürler!"))
            return
        db = _find_db(self)
        if db is not None:
            outbox_add(db, body)
            self.msg.clear()
            info(self, t("✉  Admin ile iletişime geç"),
                 t("Mesajınız kaydedildi; bağlantı kurulunca program kendiliğinden yöneticiye gönderecek. Teşekkürler!"))
        else:
            info(self, t("✉  Admin ile iletişime geç"),
                 t("Mesaj gönderilemedi. İnternet bağlantınızı kontrol edip tekrar deneyin."))

    def _mail(self):
        if self._ready():
            q = urllib.parse.urlencode({"subject": self._subject(), "body": self._body()}, quote_via=urllib.parse.quote)
            QDesktopServices.openUrl(QUrl(f"mailto:{admin_email()}?{q}"))

    def _gmail(self):
        if self._ready():
            q = urllib.parse.urlencode({"view": "cm", "fs": "1", "to": admin_email(), "su": self._subject(),
                                        "body": self._body()})
            QDesktopServices.openUrl(QUrl("https://mail.google.com/mail/?" + q))

    def _copy(self):
        if self._ready():
            QGuiApplication.clipboard().setText(f"{self._subject()}\n\n{self._body()}")
            info(self, t("📋  Kopyala"), t("Mesaj kopyalandı."))


# ---------------------------------------------------------------------- admin mesajı gönderimi + giden kutusu
# FormSubmit gönderen siteyi bir kez etkinleştirmeyi ister; etkinleştirilmiş site Referer olarak gönderilir
_FS_SITE = "https://formsubmit.co"
_FS_REFERER = _FS_SITE + "/"
_INBOX = ("https://firestore.googleapis.com/v1/projects/comm-calc-103111111/databases/(default)/documents/"
          "mesajlar?key=AIzaSyB12RFS6ENPpmnnPsETfjedNH-3hmNWQvA")


def _fs_result(text):
    """FormSubmit cevabı → "ok" | "activation" (yönetici formu henüz etkinleştirmedi) | "fail"."""
    import json
    try:
        j = json.loads(text or "{}")
    except ValueError:
        return "fail"
    if str(j.get("success")).lower() == "true":
        return "ok"
    return "activation" if "activat" in str(j.get("message", "")).lower() else "fail"


def _log(msg):
    """Gönderim sonuçları <veri>\\admin-mesaj.log dosyasına yazılır (sorun ararken işe yarar)."""
    try:
        from .paths import data_dir
        with open(data_dir() / "admin-mesaj.log", "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + str(msg)[:400] + "\n")
    except Exception:
        pass


def _inbox_post(body):
    """Yöneticinin mesaj kutusuna (Firestore "mesajlar", yalnızca ekleme) yazar → True/False."""
    import json
    import urllib.request
    F = lambda v: {"stringValue": str(v or "")[:4000]}
    fields = {"mesaj": F(body.get("Mesaj")), "konu": F("Organizer · " + str(body.get("Konu") or "Mesaj")),
              "dil": F(body.get("Dil")), "surum": F(body.get("Surum")), "platform": F("Organizer · " + str(body.get("Cihaz") or "")),
              "zaman": {"timestampValue": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}}
    if body.get("Ulasma") and body.get("Ulasma") != "-":
        fields["iletisim"] = F(body.get("Ulasma"))
    try:
        req = urllib.request.Request(_INBOX, data=json.dumps({"fields": fields}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as r:
            ok = 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        _log(f"kutu: {e!r}")
        ok = False
    _log("kutu: " + ("ok" if ok else "fail"))
    return ok


def feedback_post(body):
    """v.1.0.11: önce yöneticinin mesaj kutusuna, sonra e-posta kopyası olarak FormSubmit'e yollar; biri kabul
    ederse "ok". Aksi halde FormSubmit sonucu ("activation" | "fail") döner ve mesaj giden kutusunda bekler."""
    inbox_ok = _inbox_post(body)
    res = _feedback_mail(body)
    return "ok" if inbox_ok else res


def _feedback_mail(body):
    """Mesajı FormSubmit'e yollar. Önce Python ile, olmazsa Windows PowerShell ile (Windows'un kendi
    bağlantı yığını) dener. FormSubmit, Referer/Origin başlığı olmayan isteği reddettiği için ikisi de eklenir."""
    import json
    import urllib.error
    import urllib.request
    from . import __version__
    url = "https://formsubmit.co/ajax/" + admin_email()
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    hdr = {"Content-Type": "application/json", "Accept": "application/json", "Referer": _FS_REFERER,
           "Origin": _FS_SITE, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Organizer/" + __version__}
    res = "fail"
    try:
        req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=25) as r:
            res = _fs_result(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            res = _fs_result(e.read().decode("utf-8", "replace"))
        except Exception:
            res = "fail"
        _log(f"python HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        _log(f"python: {e!r}")
    if res == "fail" and sys.platform == "win32":
        res = _post_powershell(url, data, hdr) or res
    _log("sonuç: " + res)
    return res


def _post_powershell(url, data, hdr):
    import base64
    import subprocess
    b64 = base64.b64encode(data).decode()
    ps = ("[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
          "$b=[Convert]::FromBase64String('" + b64 + "');"
          "$h=@{'Accept'='application/json';'Referer'='" + hdr["Referer"] + "';'Origin'='" + hdr["Origin"] + "'};"
          "try{$r=Invoke-WebRequest -UseBasicParsing -Uri '" + url + "' -Method Post -Headers $h "
          "-ContentType 'application/json; charset=utf-8' -Body $b -TimeoutSec 25;"
          "[Console]::Out.Write($r.Content)}catch{[Console]::Out.Write('{}')}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        res = _fs_result(out.stdout.decode("utf-8", "replace").strip())
        _log("powershell: " + res)
        return res if res != "fail" else None
    except Exception as e:  # noqa: BLE001
        _log(f"powershell: {e!r}")
        return None


def _find_db(widget):
    w = widget
    while w is not None:
        if getattr(w, "db", None) is not None:
            return w.db
        w = w.parent()
    from PySide6.QtWidgets import QApplication
    for top in QApplication.topLevelWidgets():
        if getattr(top, "db", None) is not None:
            return top.db
    return None


def outbox_add(db, body):
    import json
    try:
        box = json.loads(db.get_setting("admin_outbox") or "[]")
    except ValueError:
        box = []
    box.append(body)
    db.set_setting("admin_outbox", json.dumps(box[-50:], ensure_ascii=False))


def outbox_flush(db):
    """Bekleyen mesajları arka planda göndermeyi dener (açılışta ve 15 dakikada bir).
    Veritabanına yalnızca ana iş parçacığında dokunulur."""
    import json
    import threading
    try:
        box = json.loads(db.get_setting("admin_outbox") or "[]")
    except ValueError:
        box = []
    if not box:
        return
    results = {}

    def work():
        for i, b in enumerate(box):
            r = feedback_post(b)
            results[i] = r
            if r != "ok":
                break                              # bağlantı yok / form etkin değil: sonra yine denenir

    th = threading.Thread(target=work, daemon=True)
    th.start()

    def poll():
        if th.is_alive():
            QTimer.singleShot(500, poll)
            return
        sent = [box[i] for i, r in results.items() if r == "ok"]
        if sent:
            try:
                cur = json.loads(db.get_setting("admin_outbox") or "[]")
            except ValueError:
                cur = []
            rest = [b for b in cur if b not in sent]
            db.set_setting("admin_outbox", json.dumps(rest, ensure_ascii=False) if rest else None)

    QTimer.singleShot(500, poll)
