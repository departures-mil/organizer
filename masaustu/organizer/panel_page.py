"""2.3.0 — Ana sayfa paneli: toplam eşya / adet / değer, azalanlar, ödünçtekiler, garantisi ve son kullanma
tarihi yaklaşanlar, son eklenenler, son değişenler, kategoriye göre değer. Satıra tıklayınca eşya açılır."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import filtre
from .common import fmt_date, fmt_price
from .db import CURRENCIES, Database
from .ek_arayuz import fmt_day, status_text
from .extras import overdue_days
from .i18n import t

LIST_MAX = 8

from fccore._icons import PATHS  # noqa: E402  (uygulamaya özgü simgeler; çizgi stili aynı)
PATHS.setdefault("cart", '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/>'
                         '<path d="M2 3h3l2.4 11.2a1 1 0 0 0 1 .8h9.7a1 1 0 0 0 1-.8L21 7H6"/>')
PATHS.setdefault("users", '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 4.6a3.2 3.2 0 0 1 0 6.3"/>'
                          '<path d="M18 14.5A6 6 0 0 1 21 20"/>')
PATHS.setdefault("plus", '<path d="M12 5v14M5 12h14"/>')
PATHS.setdefault("history", '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>')
PATHS.setdefault("folder", '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>')


def _value_text(totals):
    order = ["USD"] + [c for c, *_ in CURRENCIES if c != "USD"]
    return "  +  ".join(fmt_price(totals[c], c) for c in order if c in totals) or "—"


class Tile(QWidget):
    def __init__(self, title, value, sub="", on_click=None):
        super().__init__()
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        a = QLabel(title)
        a.setProperty("fc", "muted")
        a.setObjectName("Muted")
        b = QLabel(value)
        b.setStyleSheet("font-size: 22pt; font-weight: 700;")
        b.setWordWrap(True)
        v.addWidget(a)
        v.addWidget(b)
        c = QLabel(sub or " ")
        c.setObjectName("Muted")
        c.setWordWrap(True)
        v.addWidget(c)
        v.addStretch(1)
        if on_click:
            self.setCursor(Qt.PointingHandCursor)
            self.mousePressEvent = lambda e: on_click()


class PanelPage(QScrollArea):
    open_item = Signal(int)
    open_filter = Signal(object)     # gelişmiş filtre sözlüğü → Eşyalarım sayfasında uygulanır

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.host = None
        self.refresh()

    def warn_days(self):
        try:
            return max(1, int(self.db.get_setting("warn_days", str(filtre.WARN_DAYS)) or filtre.WARN_DAYS))
        except ValueError:
            return filtre.WARN_DAYS

    def refresh(self):
        from fccore.widgets import Card, Columns
        self.host = QWidget()
        self.host.setObjectName("fcContent")
        root = QVBoxLayout(self.host)
        root.setContentsMargins(0, 0, 6, 20)
        root.setSpacing(18)
        days = self.warn_days()
        items = self.db.list_items(sort="created_desc")
        n_qty = sum(d["quantity"] for d in items)
        totals = self.db.totals_by_currency(items)
        low = [d for d in items if Database.is_low(d) or d["quantity"] == 0 and d.get("min_qty")]
        loans = [d for d in items if d["loan_to"]]
        late = [d for d in loans if overdue_days(d) > 0]
        rem = filtre.reminders(items, days=days)
        no_price = sum(1 for d in items if d["price"] is None)

        tiles = QHBoxLayout()
        tiles.setSpacing(18)
        tiles.addWidget(Tile(t("Eşya"), f"{len(items):,}".replace(",", "."), t("toplam {q} adet", q=n_qty)), 1)
        tiles.addWidget(Tile(t("Toplam değer"), _value_text(totals),
                             t("{n} eşyanın fiyatı girilmemiş", n=no_price) if no_price else t("Bütün eşyaların fiyatı girilmiş ✓"),
                             on_click=(lambda: self.open_filter.emit({"flags": ["noprice"]})) if no_price else None), 2)
        tiles.addWidget(Tile(t("Az kalan / biten"), str(len(low)), t("alışveriş listesine eklendi"),
                             on_click=lambda: self.open_filter.emit({"flags": ["tobuy"]})), 1)
        tiles.addWidget(Tile(t("Ödünçte"), str(len(loans)), t("⚠ {n} gecikti", n=len(late)) if late else "",
                             on_click=lambda: self.open_filter.emit({"flags": ["loan"]})), 1)
        tiles.addWidget(Tile(t("Garanti / son kullanma"), str(len(rem)), t("{n} gün içinde biten ya da geçen", n=days),
                             on_click=lambda: self.open_filter.emit({"flags": ["warranty_soon", "warranty_over"]
                                                                       if any(k == "warranty" for _, k, _ in rem) else ["exp_soon"]})), 1)
        root.addLayout(tiles)

        grid = Columns(min_col=360, gap=18, max_cols=3)

        def list_card(title, icon, rows, empty, desc=None):
            c = Card("", title, icon, desc)
            if not rows:
                lab = QLabel(empty)
                lab.setObjectName("Muted")
                lab.setWordWrap(True)
                c.add(lab, 4)
            for item_id, text, sub, color in rows[:LIST_MAX]:
                b = QPushButton()
                b.setFlat(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("QPushButton { text-align: %s; padding: 6px 4px; border: none; }"
                                "QPushButton:hover { background: rgba(127,127,127,0.12); border-radius: 6px; }"
                                % ("right" if self.layoutDirection() == Qt.RightToLeft else "left"))
                lab = QLabel(f"<b>{_esc(text)}</b>" + (f"<br><span style='color:{color or '#7b878d'}'>{_esc(sub)}</span>" if sub else ""))
                lab.setTextFormat(Qt.RichText)
                lab.setAttribute(Qt.WA_TransparentForMouseEvents)
                lab.setWordWrap(True)
                h = QHBoxLayout(b)
                h.setContentsMargins(6, 4, 6, 4)
                h.addWidget(lab)
                b.setMinimumHeight(lab.sizeHint().height() + 10)
                b.clicked.connect(lambda _=False, i=item_id: self.open_item.emit(i))
                c.add(b, 2)
            if len(rows) > LIST_MAX:
                more = QLabel(t("… ve {n} eşya daha", n=len(rows) - LIST_MAX))
                more.setObjectName("Muted")
                c.add(more, 4)
            return c

        rem_rows = []
        for d, kind, n in rem:
            label = t("Garanti") if kind == "warranty" else t("Son kullanma")
            field = d["warranty_until"] if kind == "warranty" else d["expires_on"]
            rem_rows.append((d["id"], d["name"], f"{label}: {fmt_day(field)} · {status_text(field, days)}",
                             "#c0392b" if n < 0 else "#d97706"))
        grid.add(list_card(t("Garantisi / son kullanması yaklaşanlar"), "bell", rem_rows,
                           t("Önümüzdeki {n} gün içinde biten bir şey yok. ✓", n=days)))
        grid.add(list_card(t("Az kalanlar"), "cart", [(d["id"], d["name"], t("Adet: {q} · en az {m}", q=d["quantity"], m=d["min_qty"]),
                                                       "#d97706") for d in low], t("Azalan eşya yok. ✓")))
        grid.add(list_card(t("Ödünçtekiler"), "users", [
            (d["id"], d["name"], f"→ {d['loan_to']}" + (t(" · ⚠ {n} gün gecikti", n=overdue_days(d)) if overdue_days(d) > 0 else
                                                       (t(" · dönüş {x}", x=fmt_day(d["loan_due"])) if d["loan_due"] else "")),
             "#c0392b" if overdue_days(d) > 0 else None) for d in sorted(loans, key=lambda d: -overdue_days(d))],
            t("Ödünç verilmiş eşya yok.")))
        grid.add(list_card(t("Son eklenenler"), "plus", [
            (d["id"], d["name"], " · ".join(x for x in (fmt_date(d["created_at"]).split()[0], d["location_path"]) if x), None)
            for d in items[:LIST_MAX]], t("Henüz eşya eklenmemiş.")))
        changed = self._recent_changes(items)
        grid.add(list_card(t("Son değişenler"), "history", changed, t("Henüz kayıtlı değişiklik yok.")))
        grid.add(self._category_card(items))
        root.addWidget(grid)
        root.addStretch(1)
        self.setWidget(self.host)          # QScrollArea eski içeriği kendisi siler

    def _recent_changes(self, items):
        from .ek_arayuz import entry_lines
        from .settings_page import fmt_ts
        rows = []
        for d in items:
            log = d.get("changelog") or []
            if log:
                e = log[-1]
                if e.get("a") == "eklendi" and not e.get("c"):
                    continue
                head, lines = entry_lines(e)
                rows.append((e.get("t", ""), d["id"], d["name"],
                             f"{fmt_ts(e.get('t'))} · {e.get('d', '')}" + (f" · {lines[0]}" if lines else "")))
        rows.sort(reverse=True)
        return [(i, n, s, None) for _t, i, n, s in rows]

    def _category_card(self, items):
        from fccore.widgets import Card
        c = Card("", t("Kategoriye göre"), "folder")
        groups = {}
        for d in items:
            top = (d["category_path"] or t("Belirtilmemiş")).split(" › ")[0]
            g = groups.setdefault(top, {"n": 0, "q": 0, "v": {}})
            g["n"] += 1
            g["q"] += d["quantity"]
            if d["price"] is not None:
                g["v"][d["currency"]] = g["v"].get(d["currency"], 0) + d["price"]
        if not groups:
            lab = QLabel(t("Henüz eşya eklenmemiş."))
            lab.setObjectName("Muted")
            c.add(lab, 4)
            return c
        biggest = max(g["n"] for g in groups.values())
        for name, g in sorted(groups.items(), key=lambda x: -x[1]["n"])[:10]:
            row = QWidget()
            h = QVBoxLayout(row)
            h.setContentsMargins(0, 4, 0, 4)
            h.setSpacing(3)
            top = QLabel(f"<b>{_esc(name)}</b> · {g['n']} " + _esc(t("eşya")) +
                         (f" · {_esc(_value_text(g['v']))}" if g["v"] else ""))
            top.setTextFormat(Qt.RichText)
            bar = QWidget()
            bar.setFixedHeight(6)
            bar.setFixedWidth(max(8, int(260 * g["n"] / biggest)))
            bar.setStyleSheet("background: #2f8f9d; border-radius: 3px;")
            h.addWidget(top)
            h.addWidget(bar)
            c.add(row)
        return c


def _esc(s):
    from html import escape
    return escape(str(s or ""))
