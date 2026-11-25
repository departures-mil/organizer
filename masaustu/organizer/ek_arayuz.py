"""2.3.0 arayüz ekleri: arka plan işçisi, tarih alanı, Asistan (soru-cevap), çeviri menüsü,
değişiklik geçmişi ve gelişmiş filtre pencereleri."""
from datetime import datetime

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPlainTextEdit,
                               QPushButton, QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from . import filtre
from .common import confirm, info
from .db import CURRENCIES
from .i18n import t

_alive = set()   # çalışan işçiler (çöp toplayıcı erken silmesin)


class Worker(QThread):
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, fn, *a, **kw):
        super().__init__()
        self.fn, self.a, self.kw = fn, a, kw

    def run(self):
        try:
            self.done.emit(self.fn(*self.a, **self.kw))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(e)


def run_async(fn, on_done, on_fail=None, *a, **kw):
    w = Worker(fn, *a, **kw)
    _alive.add(w)
    w.done.connect(on_done)
    if on_fail:
        w.failed.connect(on_fail)
    w.finished.connect(lambda: _alive.discard(w))
    w.start()
    return w


def ai_error_text(e):
    from .zeka import AiError
    if isinstance(e, AiError):
        return {"nokey": t("Yapay zeka anahtarı girilmemiş (Ayarlar → Yapay zeka)."),
                "net": t("İnternete bağlanılamadı; çevrim dışı cevap verildi."),
                "auth": t("Yapay zeka anahtarı geçersiz. Ayarlar → Yapay zeka bölümünden kontrol edin."),
                "limit": t("Yapay zeka sağlayıcınızın günlük / dakikalık sınırı doldu. Biraz sonra yeniden deneyin."),
                }.get(e.kind, t("Yapay zeka cevap veremedi: {m}", m=e.detail[:160]))
    return str(e)


# ------------------------------------------------------------------ tarih alanı (boş bırakılabilir)
class DateField(QWidget):
    """İşaret kutusu + takvimli tarih. Değer 'YYYY-AA-GG' ya da ''."""

    def __init__(self, label, value="", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.on = QCheckBox(label)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        self.date.setLayoutDirection(Qt.LeftToRight)
        self.date.setMinimumWidth(130)
        self.left = QLabel()
        self.left.setObjectName("Muted")
        h.addWidget(self.on)
        h.addWidget(self.date)
        h.addWidget(self.left)
        h.addStretch()
        self.on.toggled.connect(self._draw)
        self.date.dateChanged.connect(self._draw)
        self.set_value(value)

    def set_value(self, v):
        d = QDate.fromString(str(v or "")[:10], "yyyy-MM-dd")
        self.on.setChecked(d.isValid())
        self.date.setDate(d if d.isValid() else QDate.currentDate().addYears(1))
        self._draw()

    def value(self):
        return self.date.date().toString("yyyy-MM-dd") if self.on.isChecked() else ""

    def _draw(self, *_):
        self.date.setEnabled(self.on.isChecked())
        self.left.setText(status_text(self.value()) if self.on.isChecked() else "")


def status_text(day, days=filtre.WARN_DAYS):
    n = filtre.days_left(day)
    if n is None:
        return ""
    if n < 0:
        return t("⛔ {n} gün önce bitti", n=-n)
    if n == 0:
        return t("⚠ bugün bitiyor")
    return (t("⚠ {n} gün kaldı", n=n) if n <= days else t("{n} gün kaldı", n=n))


def fmt_day(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return str(v or "")


# ------------------------------------------------------------------ Asistan
class AskDialog(QDialog):
    """Eşyalar hakkında soru: önce çevrim içi yapay zeka (kendi anahtarınız), yoksa çevrim dışı cevap."""

    def __init__(self, db, parent=None, question=""):
        super().__init__(parent)
        from . import zeka
        self.db, self.zeka = db, zeka
        self.setWindowTitle(t("✦  Asistan"))
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        head = QLabel(t("Eşyalarınız hakkında soru sorun"))
        head.setObjectName("SectionTitle")
        lay.addWidget(head)
        self.mode = QLabel()
        self.mode.setObjectName("Muted")
        self.mode.setWordWrap(True)
        lay.addWidget(self.mode)
        row = QHBoxLayout()
        self.q = QLineEdit(question)
        self.q.setPlaceholderText(t("Örn. Kışlık montlar nerede? · Garantisi biten ne var? · Kaç ampulüm kaldı?"))
        self.q.returnPressed.connect(self.ask)
        go = QPushButton(t("Sor"))
        go.setObjectName("Primary")
        go.clicked.connect(self.ask)
        row.addWidget(self.q, 1)
        row.addWidget(go)
        lay.addLayout(row)
        chips = QHBoxLayout()
        for s in (t("Garantisi biten ne var?"), t("Kimde ödünç eşyam var?"), t("Neler azaldı?"), t("Son kullanma tarihi yaklaşanlar")):
            b = QPushButton(s)
            b.setObjectName("Tool")
            b.clicked.connect(lambda _=False, s=s: (self.q.setText(s), self.ask()))
            chips.addWidget(b)
        chips.addStretch()
        lay.addLayout(chips)
        self.out = QTextBrowser()
        self.out.setOpenExternalLinks(False)
        lay.addWidget(self.out, 1)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self._draw_mode()
        if question:
            self.ask()

    def _draw_mode(self):
        c = self.zeka.cfg()
        self.mode.setText(t("Çevrim içi: {p} (kendi anahtarınızla). İnternet yoksa cihazdaki kayıtlardan cevaplanır.",
                            p=self.zeka.provider_info(c["provider"])[1]) if c else
                          t("Çevrim dışı cevap (cihazdaki kayıtlardan). Daha akıllı cevaplar için Ayarlar → Yapay zeka "
                            "bölümüne kendi ücretsiz anahtarınızı girin."))

    def _items(self):
        return self.db.list_items(sort="name_asc")

    def ask(self):
        q = self.q.text().strip()
        if not q:
            return
        items = self._items()
        offline = "<br>".join(_html(x) for x in self.zeka.ask_offline(q, items, t))
        if not self.zeka.cfg():
            self.out.setHtml(f"<p><b>{_html(q)}</b></p><p>{offline}</p>")
            return
        self.out.setHtml(f"<p><b>{_html(q)}</b></p><p><i>{_html(t('Düşünüyor…'))}</i></p>")
        today = datetime.now().strftime("%Y-%m-%d")

        def done(text):
            try:
                self.out.setHtml(f"<p><b>{_html(q)}</b></p><p>{_html(text).replace(chr(10), '<br>')}</p>"
                                 f"<p style='color:#7b878d'>✦ {_html(t('Çevrim içi yapay zeka'))}</p>")
            except RuntimeError:
                pass

        def failed(e):
            try:
                self.out.setHtml(f"<p><b>{_html(q)}</b></p><p>{offline}</p>"
                                 f"<p style='color:#b7791f'>{_html(ai_error_text(e))}</p>")
            except RuntimeError:
                pass
        run_async(self.zeka.ask_online, done, failed, q, items, _lang(), today)


def _lang():
    from . import i18n
    return i18n.LANG


def _html(s):
    from html import escape
    return escape(str(s or ""))


# ------------------------------------------------------------------ çeviri
LANG_LABELS = (("tr", "Türkçe"), ("en", "English"), ("ar", "العربية"))


def translate_button(target_widget, parent):
    """Bir metin alanının yanına konan "🌐" düğmesi: TR / EN / AR'ye çevirir, sonucu gösterir."""
    b = QPushButton("🌐")
    b.setToolTip(t("Çevir (Türkçe · İngilizce · Arapça) — internet yoksa çevrim dışı sözlükle"))
    b.setFixedWidth(40)

    def text():
        return target_widget.toPlainText() if isinstance(target_widget, QPlainTextEdit) else target_widget.text()

    def go(dst):
        src_text = text().strip()
        if not src_text:
            info(parent, t("Çevir"), t("Önce çevrilecek metni yazın."))
            return
        from . import ceviri
        b.setEnabled(False)
        b.setText("…")

        def done(res):
            try:
                b.setEnabled(True)
                b.setText("🌐")
                TranslateResult(src_text, res[0], res[1], dst, target_widget, parent).exec()
            except RuntimeError:
                pass

        def failed(e):
            try:
                b.setEnabled(True)
                b.setText("🌐")
                info(parent, t("Çevir"), str(e))
            except RuntimeError:
                pass
        run_async(ceviri.translate, done, failed, src_text, dst)

    def menu():
        m = QMenu(b)
        for code, name in LANG_LABELS:
            m.addAction(t("→ {x}", x=name), lambda c=code: go(c))
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))
    b.clicked.connect(menu)
    return b


class TranslateResult(QDialog):
    def __init__(self, src, out, mode, dst, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle(t("Çeviri"))
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        how = {"ai": t("✦ Yapay zeka ile çevrildi"), "web": t("🌐 Çevrim içi çeviri servisiyle çevrildi"),
               "offline": t("📖 Çevrim dışı sözlükle kelime kelime çevrildi (yaklaşık) — internet olunca daha iyi çeviri alınır")}
        note = QLabel(how.get(mode, ""))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.box = QPlainTextEdit(out)
        if dst == "ar":
            self.box.setLayoutDirection(Qt.RightToLeft)
        lay.addWidget(self.box, 1)
        row = QHBoxLayout()
        rep = QPushButton(t("Yerine yaz"))
        rep.setObjectName("Primary")
        rep.clicked.connect(self._replace)
        add = QPushButton(t("Altına ekle"))
        add.clicked.connect(self._append)
        cp = QPushButton(t("Kopyala"))
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.box.toPlainText()))
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.reject)
        for w in (rep, add, cp):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)

    def _set(self, v):
        if isinstance(self.target, QPlainTextEdit):
            self.target.setPlainText(v)
        else:
            self.target.setText(v)

    def _get(self):
        return self.target.toPlainText() if isinstance(self.target, QPlainTextEdit) else self.target.text()

    def _replace(self):
        self._set(self.box.toPlainText().strip())
        self.accept()

    def _append(self):
        cur = self._get().rstrip()
        sep = "\n" if isinstance(self.target, QPlainTextEdit) else " / "
        self._set((cur + sep if cur else "") + self.box.toPlainText().strip())
        self.accept()


# ------------------------------------------------------------------ değişiklik geçmişi
FIELD_NAMES = {
    "name": "Adı", "quantity": "Adet", "category": "Kategori", "location": "Yer", "price": "Fiyat",
    "currency": "Para birimi", "notes": "Notlar", "shop_name": "Dükkan/Kişi Adı", "shop_place": "Dükkan/Kişi Yeri",
    "shop_phone": "İletişim numarası", "min_qty": "En az adet", "to_buy": "Alışveriş listesi", "loan_to": "Ödünç",
    "loan_due": "Dönüş günü", "trashed_at": "Çöp kutusu", "warranty_until": "Garanti bitişi",
    "expires_on": "Son kullanma tarihi", "photos": "Fotoğraf", "price_auto": "Otomatik fiyat",
}
ACTIONS = {"eklendi": "➕ Eklendi", "silindi": "🗑 Çöp kutusuna taşındı", "geri_yuklendi": "↩ Çöp kutusundan geri yüklendi",
           "geri_alindi": "↶ Geri alındı", "yedekten": "💾 Yedekten geri yüklendi"}


def entry_lines(e):
    """Geçmiş kaydı → (başlık, [değişiklik satırları])."""
    from .settings_page import fmt_ts
    who = e.get("d") or "?"
    if e.get("u"):
        who += f" · {e['u']}"
    head = f"{fmt_ts(e.get('t'))} — {who}"
    lines = []
    if e.get("a") in ACTIONS:
        lines.append(t(ACTIONS[e["a"]]))
    for f, old, new in e.get("c") or []:
        name = t(FIELD_NAMES.get(f, f))
        if f in ("to_buy", "price_auto"):
            old, new = (t("evet") if old == "1" else t("hayır")), (t("evet") if new == "1" else t("hayır"))
        elif f == "trashed_at":
            if e.get("a") in ("silindi", "geri_yuklendi"):
                continue
            old, new = (t("evet") if old else t("hayır")), (t("evet") if new else t("hayır"))
        elif f == "photos":
            lines.append(t("{f}: {a} → {b} adet", f=name, a=old or "0", b=new or "0"))
            continue
        elif f in ("warranty_until", "expires_on", "loan_due"):
            old, new = fmt_day(old) if old else "", fmt_day(new) if new else ""
        lines.append(f"{name}: {old or '—'} → {new or '—'}")
    return head, lines


class HistoryDialog(QDialog):
    def __init__(self, db, item_id, parent=None):
        super().__init__(parent)
        it = db.get_item(item_id) or {"name": ""}
        self.setWindowTitle(t("Değişiklik geçmişi — {x}", x=it["name"]))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        hint = QLabel(t("Kim, hangi cihazdan, ne zaman neyi değiştirdi. Cihazlar arasında eşitlenir (son {n} değişiklik).",
                        n=40))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        view = QTextBrowser()
        parts = []
        log = db.changelog(item_id)
        if not log:
            parts.append(f"<p>{_html(t('Bu eşya için henüz kayıtlı değişiklik yok (2.3.0 sürümünden önceki değişiklikler tutulmuyordu).'))}</p>")
        for e in log:
            head, lines = entry_lines(e)
            parts.append(f"<p><b>{_html(head)}</b><br>" + "<br>".join("• " + _html(x) for x in lines) + "</p>")
        view.setHtml("".join(parts))
        lay.addWidget(view, 1)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)


# ------------------------------------------------------------------ gelişmiş filtre
class FilterDialog(QDialog):
    def __init__(self, db, current=None, parent=None):
        super().__init__(parent)
        self.db = db
        f = filtre.clean(current)
        self.setWindowTitle(t("Gelişmiş filtre"))
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        prow = QHBoxLayout()
        self.pmin, self.pmax = QDoubleSpinBox(), QDoubleSpinBox()
        for w, v in ((self.pmin, f["price_min"]), (self.pmax, f["price_max"])):
            w.setRange(-1, 1e12)
            w.setDecimals(2)
            w.setSpecialValueText("—")
            w.setValue(-1 if v is None else v)
            w.setMinimumWidth(120)
        self.cur = QComboBox()
        self.cur.addItem(t("Hepsi"), "")
        for code, sym, name in CURRENCIES:
            self.cur.addItem(f"{sym}  {t(name)}", code)
        self.cur.setCurrentIndex(max(0, self.cur.findData(f["currency"])))
        prow.addWidget(self.pmin)
        prow.addWidget(QLabel("—"))
        prow.addWidget(self.pmax)
        prow.addWidget(self.cur)
        prow.addStretch()
        form.addRow(t("Fiyat aralığı:"), prow)

        qrow = QHBoxLayout()
        self.qmin, self.qmax = QSpinBox(), QSpinBox()
        for w, v in ((self.qmin, f["qty_min"]), (self.qmax, f["qty_max"])):
            w.setRange(-1, 1_000_000)
            w.setSpecialValueText("—")
            w.setValue(-1 if v is None else v)
        qrow.addWidget(self.qmin)
        qrow.addWidget(QLabel("—"))
        qrow.addWidget(self.qmax)
        qrow.addStretch()
        form.addRow(t("Adet aralığı:"), qrow)

        drow = QHBoxLayout()
        self.dfrom = DateField(t("başlangıç"), f["date_from"])
        self.dto = DateField(t("bitiş"), f["date_to"])
        for w in (self.dfrom, self.dto):
            w.left.hide()
            drow.addWidget(w)
        form.addRow(t("Ekleme tarihi:"), drow)

        self.shop = QLineEdit(f["shop"])
        self.shop.setPlaceholderText(t("Dükkan / kişi adı, yeri ya da numarası"))
        from PySide6.QtWidgets import QCompleter
        comp = QCompleter(sorted(db.known_shops(), key=str.lower), self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.shop.setCompleter(comp)
        form.addRow(t("Satın alındığı yer:").rstrip(":") + ":", self.shop)
        lay.addLayout(form)

        box = QLabel(t("Durum"))
        box.setObjectName("SectionTitle")
        lay.addWidget(box)
        grid = QGridLayout()
        self.flags = {}
        for i, (k, label) in enumerate(filtre.FLAGS):
            c = QCheckBox(t(label))
            c.setChecked(k in f["flags"])
            self.flags[k] = c
            grid.addWidget(c, i // 2, i % 2)
        lay.addLayout(grid)
        note = QLabel(t("Seçilen bütün koşullar birlikte aranır. Kategori / yer ağacı ve arama kutusu da geçerlidir."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QDialogButtonBox()
        ok = bb.addButton(t("Uygula"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        save = bb.addButton(t("💾  Filtreyi kaydet…"), QDialogButtonBox.ActionRole)
        clear = bb.addButton(t("Temizle"), QDialogButtonBox.ResetRole)
        bb.addButton(t("Vazgeç"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        save.clicked.connect(self._save)
        clear.clicked.connect(self._clear)
        lay.addWidget(bb)

    def value(self):
        def num(w):
            return None if w.value() < 0 else w.value()
        return filtre.clean({
            "price_min": num(self.pmin), "price_max": num(self.pmax), "currency": self.cur.currentData(),
            "qty_min": num(self.qmin), "qty_max": num(self.qmax),
            "date_from": self.dfrom.value(), "date_to": self.dto.value(), "shop": self.shop.text(),
            "flags": [k for k, c in self.flags.items() if c.isChecked()]})

    def _clear(self):
        for w in (self.pmin, self.pmax, self.qmin, self.qmax):
            w.setValue(-1)
        self.cur.setCurrentIndex(0)
        self.dfrom.set_value("")
        self.dto.set_value("")
        self.shop.clear()
        for c in self.flags.values():
            c.setChecked(False)

    def _save(self):
        if not filtre.is_active(self.value()):
            info(self, t("Gelişmiş filtre"), t("Kaydetmek için önce en az bir koşul seçin."))
            return
        name, ok = QInputDialog.getText(self, t("Filtreyi kaydet"), t("Filtrenin adı:"))
        if ok and name.strip():
            filtre.save(self.db, name, self.value())
            info(self, t("Gelişmiş filtre"), t("„{x}“ kaydedildi. „Filtre ▾“ menüsünden tek tıkla açabilirsiniz.", x=name.strip()))


def saved_menu(db, parent, on_apply, on_open):
    """„Filtre ▾“ menüsü: gelişmiş filtre · kayıtlı filtreler · kayıtlı filtreyi sil."""
    m = QMenu(parent)
    m.addAction(t("⚙  Gelişmiş filtre…"), on_open)
    lst = filtre.saved(db)
    if lst:
        m.addSeparator()
        for x in lst:
            m.addAction("★  " + x["name"], lambda f=x["f"]: on_apply(f))
        sub = m.addMenu(t("Kayıtlı filtreyi sil"))
        for x in lst:
            sub.addAction(x["name"], lambda n=x["name"]: confirm(parent, t("Sil"), t("„{x}“ filtresi silinsin mi?", x=n),
                                                                  yes=t("Sil"), danger=True) and filtre.remove(db, n))
    m.addSeparator()
    quick = m.addMenu(t("Hızlı filtre"))
    for k, label in filtre.FLAGS:
        quick.addAction(t(label), lambda k=k: on_apply({"flags": [k]}))
    return m
