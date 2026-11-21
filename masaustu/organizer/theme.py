from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .paths import asset

TEAL = "#2a9d8f"
TEAL_DARK = "#1d5f74"
SAND = "#f6bd60"
ORANGE = "#f28c38"
INK = "#20323a"
MUTED = "#6b8590"

def _url(name):
    return asset(name).replace("\\", "/")


# v.1.0.8: açık / koyu görünüm. DARK: build_style() ve arka plan bunu kullanır (Ayarlar → Görünüm).
DARK = False
PALETTES = {
    "light": {"bg": "#fbf6ee", "card": "rgba(255,255,255,0.90)", "cardline": "rgba(29,95,116,0.10)", "ink": INK,
              "muted": MUTED, "badge": "#e6f3f1", "photobox": "#f2efe8", "btn": "#ffffff", "border": "#c9dadd",
              "hover": "#f2faf9", "pressed": "#e3f3f1", "disabled": "#a9b8bd", "disline": "#e1e8ea",
              "dangerbg": "#fdf0ee", "input": "#ffffff", "sel": "#d6efec", "header": "#2f3e46",
              "headerhover": "#3d515b", "headerline": "#ffffff", "title": TEAL_DARK, "scroll": "rgba(29,95,116,0.25)",
              "banner": "#fff6e5", "bannerline": "#f6bd60"},
    "dark": {"bg": "#111a1e", "card": "rgba(27,38,44,0.94)", "cardline": "rgba(127,209,197,0.12)", "ink": "#e2ebee",
             "muted": "#93a9b2", "badge": "#1d3a3a", "photobox": "#18242a", "btn": "#1d2a30", "border": "#36494f",
             "hover": "#22343a", "pressed": "#294047", "disabled": "#5d6f75", "disline": "#2a3a40",
             "dangerbg": "#3a2220", "input": "#18242a", "sel": "#22484a", "header": "#0c1417",
             "headerhover": "#1c2b31", "headerline": "#1b262c", "title": "#7fd1c5", "scroll": "rgba(127,209,197,0.25)",
             "banner": "#33291a", "bannerline": "#8a6a2e"},
}


def color(key):
    """Seçili görünümdeki renk (satır içi stiller için)."""
    return PALETTES["dark" if DARK else "light"][key]


def system_dark():
    """Windows / sistem koyu temada mı?"""
    try:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve_dark(mode):
    """mode: "light" | "dark" | "auto" """
    return system_dark() if mode == "auto" else mode == "dark"


def build_style(rtl=False, dark=None):
    align = "right" if rtl else "left"
    if dark is None:
        dark = DARK
    P = PALETTES["dark" if dark else "light"]
    return f"""
* {{ font-family: "Segoe UI", "Noto Sans", "Noto Sans Arabic", "DejaVu Sans", sans-serif; font-size: 10.5pt; color: {P["ink"]}; }}
QMainWindow, QDialog {{ background: {P["bg"]}; }}
QFrame#Card {{ background: {P["card"]}; border-radius: 18px; border: 1px solid {P["cardline"]}; }}
QFrame#Sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {TEAL_DARK}, stop:1 #143f4d); border-radius: 22px; }}
QFrame#Sidebar QLabel {{ color: #ffffff; background: transparent; }}
QLabel#AppTitle {{ font-size: 21pt; font-weight: 700; }}
QLabel#AppSubtitle {{ color: #bfe0dc; font-size: 9.5pt; }}
QLabel#Clock {{ color: #bfe0dc; font-size: 10pt; }}
QPushButton#NavButton {{ color: #dcefee; background: transparent; border: none; text-align: {align};
    padding: 13px 14px; border-radius: 13px; font-size: 11.5pt; }}
QPushButton#NavButton:hover {{ background: rgba(255,255,255,0.10); }}
QPushButton#NavButton:checked {{ background: {SAND}; color: #1d3b45; font-weight: 600; }}
QLabel#PageTitle {{ font-size: 22pt; font-weight: 700; color: {P["title"]}; background: transparent; }}
QLabel#SectionTitle {{ font-size: 12.5pt; font-weight: 700; color: {P["title"]}; background: transparent; }}
QLabel#DetailName {{ font-size: 16pt; font-weight: 700; color: {P["ink"]}; }}
QLabel#Muted {{ color: {P["muted"]}; background: transparent; }}
QLabel#FieldName {{ color: {P["muted"]}; font-size: 9.5pt; }}
QLabel#Badge {{ background: {P["badge"]}; color: {P["title"]}; border-radius: 9px; padding: 3px 9px; font-weight: 600; }}
QLabel#PhotoBox {{ background: {P["photobox"]}; border-radius: 14px; color: {P["muted"]}; }}
QPushButton {{ background: {P["btn"]}; border: 1px solid {P["border"]}; border-radius: 10px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {TEAL}; background: {P["hover"]}; }}
QPushButton:pressed {{ background: {P["pressed"]}; }}
QPushButton:disabled {{ color: {P["disabled"]}; border-color: {P["disline"]}; }}
QPushButton#Primary {{ background: {TEAL}; color: white; border: none; font-weight: 600; padding: 9px 18px; }}
QPushButton#Primary:hover {{ background: #238a7e; }}
QPushButton#Danger {{ color: #c0392b; }}
QPushButton#Danger:hover {{ border-color: #c0392b; background: {P["dangerbg"]}; }}
QPushButton#Round {{ min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0;
    border-radius: 15px; font-size: 13pt; font-weight: 700; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 2px; }}
QToolButton:hover:enabled {{ background: rgba(42,157,143,0.15); }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit {{
    background: {P["input"]}; border: 1px solid {P["border"]}; border-radius: 9px; padding: 6px 8px;
    selection-background-color: {TEAL}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {TEAL}; }}
QLineEdit#Search {{ padding: 9px 16px; border-radius: 19px; font-size: 11pt; }}
QComboBox QAbstractItemView {{ background: {P["input"]}; color: {P["ink"]}; selection-background-color: {P["sel"]}; selection-color: {P["ink"]}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: transparent; border: none;
    alternate-background-color: rgba(42,157,143,0.05);
    selection-background-color: rgba(42,157,143,0.22); selection-color: {P["ink"]}; outline: 0; }}
QTreeWidget::item {{ padding: 5px 2px; border-radius: 6px; }}
QTreeWidget::item:selected {{ background: rgba(42,157,143,0.22); color: {P["ink"]}; }}
QTableWidget::item {{ padding: 4px; }}
QHeaderView {{ background: {P["header"]}; border: none; }}
QHeaderView::section {{ background: {P["header"]}; color: white; border: none; border-right: 2px solid {P["headerline"]};
    padding: 8px 8px; font-weight: 700; }}
QHeaderView::section:last {{ border-right: none; }}
QHeaderView::section:hover {{ background: {P["headerhover"]}; }}
QTableCornerButton::section {{ background: {P["header"]}; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; margin-right: 4px; border-bottom: 3px solid transparent;
    color: {P["muted"]}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {P["title"]}; border-bottom: 3px solid {SAND}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid #9fb8bd; border-radius: 5px; background: {P["input"]}; }}
QCheckBox::indicator:hover {{ border-color: {TEAL}; }}
QCheckBox::indicator:checked {{ background: {TEAL}; border-color: {TEAL}; image: url("{_url('check.png')}"); }}
QRadioButton {{ background: transparent; spacing: 8px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 2px solid #9fb8bd; border-radius: 10px; background: {P["input"]}; }}
QRadioButton::indicator:checked {{ border-color: {TEAL}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 {TEAL}, stop:0.5 {TEAL}, stop:0.6 {P["input"]}, stop:1 {P["input"]}); }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{_url('arrow_down.png')}"); width: 13px; height: 13px; }}
QDateTimeEdit::drop-down {{ border: none; width: 28px; }}
QDateTimeEdit::down-arrow {{ image: url("{_url('arrow_down.png')}"); width: 13px; height: 13px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; border: none; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 24px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{_url('arrow_up.png')}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{_url('arrow_down.png')}"); width: 11px; height: 11px; }}
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P["scroll"]}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {P["scroll"]}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: {P["input"]}; border: 1px solid {P["border"]}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {P["sel"]}; color: {P["ink"]}; }}
QToolTip {{ background: {TEAL_DARK}; color: white; border: none; padding: 5px 8px; border-radius: 6px; }}
QListWidget#PhotoList {{ background: {P["photobox"]}; border-radius: 12px; }}
QLabel#Banner {{ background: {P["banner"]}; color: {P["ink"]}; border: 1px solid {P["bannerline"]}; border-radius: 12px; padding: 8px 12px; }}
QPushButton#Tool {{ padding: 6px 12px; }}
QPushButton#Tool:checked {{ background: {TEAL}; color: white; border-color: {TEAL}; font-weight: 600; }}
QPushButton#Warn {{ color: #b7791f; border-color: #f0c98a; }}
QPushButton#Warn:checked {{ background: #f28c38; color: white; border-color: #f28c38; }}
QTableWidget {{ color: {P["ink"]}; }}
QTabWidget QWidget {{ background: transparent; }}
QProgressBar {{ background: {P["photobox"]}; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 4px; }}
"""


class BackgroundWidget(QWidget):
    """Yumuşak renk geçişli, noktalı desenli ve logolu arka plan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logo = QPixmap(asset("logo.png"))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        grad = QLinearGradient(0, 0, w, h)
        stops = ("#0f1d22", "#121b1f", "#1d1a16") if DARK else ("#e3f1ef", "#f7f3ea", "#fbe9d3")
        grad.setColorAt(0.0, QColor(stops[0]))
        grad.setColorAt(0.55, QColor(stops[1]))
        grad.setColorAt(1.0, QColor(stops[2]))
        p.fillRect(self.rect(), grad)

        def blob(cx, cy, r, color, alpha):
            g = QRadialGradient(QPointF(cx, cy), r)
            c = QColor(color)
            c.setAlpha(alpha)
            g.setColorAt(0, c)
            c.setAlpha(0)
            g.setColorAt(1, c)
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), r, r)

        k = 0.45 if DARK else 1.0
        blob(w * 0.88, h * 0.10, h * 0.55, TEAL, int(70 * k))
        blob(w * 0.18, h * 1.02, h * 0.60, ORANGE, int(60 * k))
        blob(w * 0.55, h * 0.55, h * 0.45, SAND, int(40 * k))

        dot = QColor("#7fd1c5" if DARK else TEAL_DARK)
        dot.setAlpha(18 if DARK else 22)
        p.setBrush(dot)
        step = 26
        for y in range(step // 2, h, step):
            offset = step // 2 if (y // step) % 2 else 0
            for x in range(offset, w, step):
                p.drawEllipse(QPointF(x, y), 1.3, 1.3)

        if not self._logo.isNull():
            size = min(460, int(h * 0.5))
            p.setOpacity(0.07)
            x = 30 if self.layoutDirection() == Qt.RightToLeft else w - size - 30
            p.drawPixmap(QRectF(x, h - size - 30, size, size).toRect(), self._logo)
        p.end()
