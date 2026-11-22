"""Sağ üst köşedeki çubuk: gizle, hızlı ara, dil, eşitle, güncelle ve pencere düğmeleri."""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from . import i18n
from .i18n import t

INK = "#1d5f74"
TEAL = "#2a9d8f"

_P = {
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1"/>'
               '<path d="M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "scan": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
            '<path d="M7 12h10"/>',
    "lang": '<path d="M4 5h9M8.5 3v2M11 5c-1 4-3.6 7-7 8.5"/><path d="M6 8.5c1.3 2 3 3.4 5 4.3"/>'
            '<path d="M13 21l4-9 4 9M14.4 18h5.2"/>',
    "cloud": '<path d="M7 18a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 8.6 4.7 4.7 0 0 1 17.5 18z"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
    "min": '<path d="M6 12h12"/>',
    "max": '<path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5"/>',
    "half": '<path d="M10 4v6H4M14 20v-6h6M4 4l6 6M20 20l-6-6"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
}


def icon(name, color=None, size=40):
    from . import theme
    color = color or ("#cfe6e8" if theme.DARK else INK)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{_P[name]}</svg>')
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


_STYLE = """
QFrame#TopBar {{ background: transparent; }}
QPushButton#TbIcon, QPushButton#TbPill, QPushButton#TbWin {{
    background: rgba(255,255,255,0.92); border: 1px solid #cfe0e2; border-radius: 11px; }}
QPushButton#TbIcon, QPushButton#TbWin {{ min-width: 38px; max-width: 38px; min-height: 36px; max-height: 36px; padding: 0; }}
QPushButton#TbPill {{ min-height: 36px; max-height: 36px; padding: 0 14px; font-weight: 600; color: {INK}; }}
QPushButton#TbIcon:hover, QPushButton#TbPill:hover, QPushButton#TbWin:hover {{ border-color: {TEAL}; background: #f2faf9; }}
QPushButton#TbIcon:checked {{ background: #e3f3f1; border-color: {TEAL}; }}
QPushButton#TbClose:hover {{ background: #fdecea; border-color: #e05a47; }}
QPushButton#TbPill:disabled {{ color: #8aa3aa; }}
QFrame#TbLang {{ background: rgba(255,255,255,0.92); border: 1px solid #cfe0e2; border-radius: 11px; }}
QFrame#TbLang QLabel {{ background: transparent; padding-left: 8px; }}
QPushButton#TbLangBtn {{ background: transparent; border: none; border-radius: 8px; min-width: 36px; min-height: 28px;
    padding: 0 4px; font-weight: 700; color: #6b8590; }}
QPushButton#TbLangBtn:hover {{ color: {INK}; }}
QPushButton#TbLangBtn:checked {{ background: #d6efec; color: {INK}; }}
QFrame#TbGroup {{ background: transparent; }}
QLabel#TbInfo {{ color: #6b8590; font-size: 9.5pt; background: transparent; }}
"""


def style():
    from . import theme
    s = _STYLE.format(INK=INK, TEAL=TEAL)
    if theme.DARK:
        s = (s.replace("rgba(255,255,255,0.92)", "#1d2a30").replace("#cfe0e2", "#36494f")
              .replace("#f2faf9", "#22343a").replace("#e3f3f1", "#294047").replace("#d6efec", "#22484a")
              .replace(f"color: {INK}", "color: #cfe6e8").replace("#fdecea", "#4a2421"))
    return s


class TopBar(QFrame):
    hide_toggled = Signal(bool)
    scan_clicked = Signal()
    language_changed = Signal(str)
    sync_clicked = Signal()
    update_clicked = Signal()
    minimize_clicked = Signal()
    size_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, hidden=False, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setStyleSheet(style())
        self.setLayoutDirection(Qt.LeftToRight)   # her dilde düğmeler sağ üst köşede dursun
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.info = QLabel()
        self.info.setObjectName("TbInfo")
        self.info.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        lay.addWidget(self.info, 1)

        self.eye = self._icon_btn("eye-off" if hidden else "eye",
                                  t("Fiyatları gizle / göster"), checkable=True)
        self.eye.setChecked(hidden)
        self.eye.toggled.connect(self._eye)
        lay.addWidget(self.eye)

        self.scan = self._icon_btn("scan", t("Hızlı ara / barkod okuyucu (Ctrl+F)"))
        self.scan.clicked.connect(self.scan_clicked)
        lay.addWidget(self.scan)

        lang = QFrame()
        lang.setObjectName("TbLang")
        ll = QHBoxLayout(lang)
        ll.setContentsMargins(4, 3, 4, 3)
        ll.setSpacing(2)
        li = QLabel()
        li.setPixmap(icon("lang", "#6b8590").pixmap(QSize(18, 18)))
        ll.addWidget(li)
        group = QButtonGroup(self)
        for code, label in (("tr", "TR"), ("en", "EN"), ("ar", "AR")):
            b = QPushButton(label)
            b.setObjectName("TbLangBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(i18n.LANG == code)
            b.clicked.connect(lambda _=False, c=code: self.language_changed.emit(c))
            group.addButton(b)
            ll.addWidget(b)
        lay.addWidget(lang)

        self.sync_btn = self._pill("cloud", t("Eşitle"))
        self.sync_btn.clicked.connect(self.sync_clicked)
        lay.addWidget(self.sync_btn)

        self.update_btn = self._pill("download", t("Güncelle"))
        self.update_btn.clicked.connect(self.update_clicked)
        lay.addWidget(self.update_btn)

        win = QFrame()
        win.setObjectName("TbGroup")
        wl = QHBoxLayout(win)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(6)
        self.min_btn = self._icon_btn("min", t("Simge durumuna küçült"), obj="TbWin")
        self.min_btn.clicked.connect(self.minimize_clicked)
        self.size_btn = self._icon_btn("half", t("Yarım ekran"), obj="TbWin")
        self.size_btn.clicked.connect(self.size_clicked)
        self.close_btn = self._icon_btn("close", t("Kapat"), obj="TbWin")
        self.close_btn.setStyleSheet("QPushButton:hover { background: #fdecea; border-color: #e05a47; }")
        self.close_btn.clicked.connect(self.close_clicked)
        for b in (self.min_btn, self.size_btn, self.close_btn):
            wl.addWidget(b)
        lay.addWidget(win)

    def add_before_update(self, w):
        lay = self.layout()
        i = lay.indexOf(self.update_btn)
        lay.insertWidget(i if i >= 0 else lay.count(), w)

    # ------------------------------------------------------------ yapı
    def _icon_btn(self, name, tip, checkable=False, obj="TbIcon"):
        b = QPushButton()
        b.setObjectName(obj)
        b.setIcon(icon(name))
        b.setIconSize(QSize(19, 19))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _pill(self, name, text):
        b = QPushButton(" " + text)
        b.setObjectName("TbPill")
        b.setIcon(icon(name, TEAL))
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _eye(self, on):
        self.eye.setIcon(icon("eye-off" if on else "eye"))
        self.hide_toggled.emit(on)

    # ------------------------------------------------------------ durum
    def set_window_state(self, full):
        self.size_btn.setIcon(icon("half" if full else "max"))
        self.size_btn.setToolTip(t("Yarım ekran") if full else t("Tam ekran"))

    def set_sync(self, text, busy, enabled=True):
        self.sync_btn.setText(" " + (t("Eşitleniyor…") if busy else t("Eşitle")))
        self.sync_btn.setEnabled(enabled and not busy)
        self.sync_btn.setToolTip(text)

    def set_info(self, text):
        self.info.setText(text)

    def set_update(self, text, tip="", highlight=False, enabled=True):
        self.update_btn.setText(" " + text)
        self.update_btn.setToolTip(tip)
        self.update_btn.setEnabled(enabled)
        self.update_btn.setIcon(icon("download", "white" if highlight else TEAL))
        self.update_btn.setStyleSheet(
            "QPushButton { background: #f28c38; color: white; border-color: #f28c38; }"
            "QPushButton:hover { background: #e07b28; }" if highlight else "")
