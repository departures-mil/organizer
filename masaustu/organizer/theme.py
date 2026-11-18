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


def build_style(rtl=False):
    align = "right" if rtl else "left"
    return f"""
* {{ font-family: "Segoe UI", "Noto Sans", "Noto Sans Arabic", "DejaVu Sans", sans-serif; font-size: 10.5pt; color: {INK}; }}
QMainWindow, QDialog {{ background: #fbf6ee; }}
QFrame#Card {{ background: rgba(255,255,255,0.90); border-radius: 18px; border: 1px solid rgba(29,95,116,0.10); }}
QFrame#Sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {TEAL_DARK}, stop:1 #143f4d); border-radius: 22px; }}
QFrame#Sidebar QLabel {{ color: #ffffff; background: transparent; }}
QLabel#AppTitle {{ font-size: 21pt; font-weight: 700; }}
QLabel#AppSubtitle {{ color: #bfe0dc; font-size: 9.5pt; }}
QLabel#Clock {{ color: #bfe0dc; font-size: 10pt; }}
QPushButton#NavButton {{ color: #dcefee; background: transparent; border: none; text-align: {align};
    padding: 13px 14px; border-radius: 13px; font-size: 11.5pt; }}
QPushButton#NavButton:hover {{ background: rgba(255,255,255,0.10); }}
QPushButton#NavButton:checked {{ background: {SAND}; color: #1d3b45; font-weight: 600; }}
QLabel#PageTitle {{ font-size: 22pt; font-weight: 700; color: {TEAL_DARK}; background: transparent; }}
QLabel#SectionTitle {{ font-size: 12.5pt; font-weight: 700; color: {TEAL_DARK}; background: transparent; }}
QLabel#DetailName {{ font-size: 16pt; font-weight: 700; color: {INK}; }}
QLabel#Muted {{ color: {MUTED}; background: transparent; }}
QLabel#FieldName {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#Badge {{ background: #e6f3f1; color: {TEAL_DARK}; border-radius: 9px; padding: 3px 9px; font-weight: 600; }}
QLabel#PhotoBox {{ background: #f2efe8; border-radius: 14px; color: {MUTED}; }}
QPushButton {{ background: #ffffff; border: 1px solid #c9dadd; border-radius: 10px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {TEAL}; background: #f2faf9; }}
QPushButton:pressed {{ background: #e3f3f1; }}
QPushButton:disabled {{ color: #a9b8bd; border-color: #e1e8ea; }}
QPushButton#Primary {{ background: {TEAL}; color: white; border: none; font-weight: 600; padding: 9px 18px; }}
QPushButton#Primary:hover {{ background: #238a7e; }}
QPushButton#Danger {{ color: #c0392b; }}
QPushButton#Danger:hover {{ border-color: #c0392b; background: #fdf0ee; }}
QPushButton#Round {{ min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0;
    border-radius: 15px; font-size: 13pt; font-weight: 700; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 2px; }}
QToolButton:hover:enabled {{ background: rgba(42,157,143,0.15); }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit {{
    background: #ffffff; border: 1px solid #c9dadd; border-radius: 9px; padding: 6px 8px;
    selection-background-color: {TEAL}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {TEAL}; }}
QLineEdit#Search {{ padding: 9px 16px; border-radius: 19px; font-size: 11pt; }}
QComboBox QAbstractItemView {{ background: white; selection-background-color: #d6efec; selection-color: {INK}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: transparent; border: none;
    alternate-background-color: rgba(42,157,143,0.05);
    selection-background-color: rgba(42,157,143,0.22); selection-color: {INK}; outline: 0; }}
QTreeWidget::item {{ padding: 5px 2px; border-radius: 6px; }}
QTreeWidget::item:selected {{ background: rgba(42,157,143,0.22); color: {INK}; }}
QTableWidget::item {{ padding: 4px; }}
QHeaderView {{ background: #2f3e46; border: none; }}
QHeaderView::section {{ background: #2f3e46; color: white; border: none; border-right: 2px solid white;
    padding: 8px 8px; font-weight: 700; }}
QHeaderView::section:last {{ border-right: none; }}
QHeaderView::section:hover {{ background: #3d515b; }}
QTableCornerButton::section {{ background: #2f3e46; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; margin-right: 4px; border-bottom: 3px solid transparent;
    color: {MUTED}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEAL_DARK}; border-bottom: 3px solid {SAND}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid #9fb8bd; border-radius: 5px; background: white; }}
QCheckBox::indicator:hover {{ border-color: {TEAL}; }}
QCheckBox::indicator:checked {{ background: {TEAL}; border-color: {TEAL}; image: url("{_url('check.png')}"); }}
QRadioButton {{ background: transparent; spacing: 8px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 2px solid #9fb8bd; border-radius: 10px; background: white; }}
QRadioButton::indicator:checked {{ border-color: {TEAL}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 {TEAL}, stop:0.5 {TEAL}, stop:0.6 white, stop:1 white); }}
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
QScrollBar::handle:vertical {{ background: rgba(29,95,116,0.25); border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(29,95,116,0.25); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: white; border: 1px solid #d5e2e4; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: #d6efec; color: {INK}; }}
QToolTip {{ background: {TEAL_DARK}; color: white; border: none; padding: 5px 8px; border-radius: 6px; }}
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
        grad.setColorAt(0.0, QColor("#e3f1ef"))
        grad.setColorAt(0.55, QColor("#f7f3ea"))
        grad.setColorAt(1.0, QColor("#fbe9d3"))
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

        blob(w * 0.88, h * 0.10, h * 0.55, TEAL, 70)
        blob(w * 0.18, h * 1.02, h * 0.60, ORANGE, 60)
        blob(w * 0.55, h * 0.55, h * 0.45, SAND, 40)

        dot = QColor(TEAL_DARK)
        dot.setAlpha(22)
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
