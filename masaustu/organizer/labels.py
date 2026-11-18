"""Ayarlar → Etiketler: programdaki her yazıyı kullanıcının kendi etiketiyle değiştirme."""
import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import i18n
from .common import confirm
from .i18n import t

SETTING = "labels_v1"


def load(db):
    i18n.set_overrides(db.get_setting(SETTING, "") or "{}")


def count(lang=None):
    return len(i18n.OVERRIDES.get(lang or i18n.LANG, {}))


_SPLIT = re.compile(r"^([^\w]*)(.*?)([:：…]?\s*)$", re.S)


def split(s):
    """'📦   Eşyalarım:' → ('📦   ', 'Eşyalarım', ':') — simge/boşluk öneki, asıl yazı, iki nokta soneki."""
    m = _SPLIT.match(s or "")
    return m.groups() if m else ("", s or "", "")


def propagate(keys, base, values, key, new):
    """Bir etiket değişince aynı yazının simgeli / iki noktalı diğer biçimleri de değişir.
    values: {anahtar: yeni yazı} (yerinde güncellenir)."""
    pk, ck, sk = split(base(key))
    if new:
        pv, cv, sv = split(new)
        values[key] = new
    for j in keys:
        if j == key:
            continue
        pj, cj, sj = split(base(j))
        if not ck or cj != ck:
            continue
        if new:
            values[j] = pj + cv + sj
        else:
            values.pop(j, None)
    if not new:
        values.pop(key, None)


def _show(s):
    return s.replace("\n", "⏎")


def _unshow(s):
    return s.replace("⏎", "\n")


class LabelEditor(QDialog):
    """Bütün etiketler bir tabloda: solda programın yazısı, sağda kullanıcının yeni etiketi (çift tıkla / yaz)."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(t("Etiketleri düzenle"))
        self.resize(980, 700)
        lay = QVBoxLayout(self)
        hint = QLabel(t("Programdaki bütün yazıları (düğmeler, başlıklar, alan adları) kendinize göre değiştirebilirsiniz. "
                        "Değişiklik yalnızca seçili dil için geçerlidir.") + "\n"
                      + t("{x} gibi yer tutucuları silmeyin; oraya sayı ya da ad gelir."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Etiket ara…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.only = QCheckBox(t("Yalnızca değiştirilenler"))
        self.only.toggled.connect(self._filter)
        top.addWidget(self.search, 1)
        top.addWidget(self.only)
        lay.addLayout(top)

        lang = i18n.LANG
        cur = dict(i18n.OVERRIDES.get(lang, {}))
        keys = list(i18n.STRINGS.keys())
        keys += [k for k in cur if k not in i18n.STRINGS]
        self.keys = keys
        self.table = QTableWidget(len(keys), 2)
        self.table.setHorizontalHeaderLabels([t("Programdaki yazı"), t("Yeni etiket (boş = değişmesin)")])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed | QAbstractItemView.SelectedClicked)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        self.initial = {}
        for r, k in enumerate(keys):
            self.initial[k] = cur.get(k, "")
            a = QTableWidgetItem(_show(i18n.base_text(k, lang)))
            a.setFlags(a.flags() & ~Qt.ItemIsEditable)
            a.setData(Qt.UserRole, k)
            a.setToolTip(i18n.base_text(k, lang))
            b = QTableWidgetItem(_show(cur.get(k, "")))
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, b)
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        reset = QPushButton(t("Hepsini sıfırla"))
        reset.setObjectName("Danger")
        reset.clicked.connect(self._reset)
        bottom.addWidget(reset)
        bottom.addStretch()
        cancel = QPushButton(t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t("Kaydet"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        lay.addLayout(bottom)

    def _filter(self, *_):
        q = i18n_norm(self.search.text())
        only = self.only.isChecked()
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0).text(), self.table.item(r, 1).text()
            hide = (q and q not in i18n_norm(a + " " + b + " " + self.keys[r])) or (only and not b.strip())
            self.table.setRowHidden(r, bool(hide))

    def _reset(self):
        if confirm(self, t("Hepsini sıfırla"), t("Bütün etiketler programın kendi yazısına dönsün mü?"), danger=True):
            for r in range(self.table.rowCount()):
                self.table.item(r, 1).setText("")

    def values(self):
        lang = i18n.LANG
        base = lambda k: i18n.base_text(k, lang)
        typed = {k: _unshow(self.table.item(r, 1).text()).strip() for r, k in enumerate(self.keys)}
        out = {k: v for k, v in typed.items() if v}
        for k in self.keys:   # elle değiştirilen satırlar, aynı yazının öbür biçimlerine de uygulanır
            if typed[k] != self.initial.get(k, ""):
                propagate(self.keys, base, out, k, typed[k])
        return {k: v for k, v in out.items() if v and v != base(k)}

    def _save(self):
        try:
            data = json.loads(self.db.get_setting(SETTING, "") or "{}")
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        vals = self.values()
        if vals:
            data[i18n.LANG] = vals
        else:
            data.pop(i18n.LANG, None)
        self.db.set_setting(SETTING, json.dumps(data, ensure_ascii=False))
        i18n.set_overrides(data)
        self.accept()


def i18n_norm(s):
    return (s or "").casefold().replace("i̇", "i").replace("ı", "i")
