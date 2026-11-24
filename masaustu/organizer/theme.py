"""Görünüm (2.2.0'dan beri ortak çekirdek fccore ile).

Renkler fccore şemasından (falcon varsayılan, klasik = 2.1 öncesinin görünümü, zumrut, …) gelir; koyu/açık/otomatik ve
yazı boyutu Ayarlar → Görünüm'den ya da üst çubuktaki tema düğmesinden değişir. Bu dosya:
  - KLASIK: eski görünümün (v.1.0.x) renkleri → style.register_scheme('klasik', …)
  - compat_qss(): uygulamanın kendi nesne adlarını (Card, PageTitle, Primary, Danger, Tool, Banner …) şema tokenlarıyla boyar
  - color(key): satır içi renkler için eski anahtarlar (ink, muted, title …) → şema tokenı
"""
from fccore import style

TEAL = "#2a9d8f"
TEAL_DARK = "#1d5f74"
SAND = "#f6bd60"
ORANGE = "#f28c38"
INK = "#20323a"
MUTED = "#6b8590"

# style.effective() == 'dark' iken True (fccore değişince kabuk günceller)
DARK = False

# ---------------------------------------------------------------- klasik şema (v.1.0.x renkleri)
KLASIK_LIGHT = {
    "bg": "#fbf6ee", "bg-grid": "#1d5f7410", "panel": "#ffffffe6", "panel-solid": "#ffffff", "panel-hover": "#f2faf9",
    "border": "#c9dadd", "border-strong": "#2a9d8f", "border-w": "1px", "text": INK, "muted": MUTED, "label": TEAL_DARK,
    "nav-text": "#dcefee", "nav-title": "#bfe0dc", "accent": TEAL, "accent-2": TEAL_DARK, "on-accent": "#ffffff",
    "primary-1": TEAL, "primary-2": "#238a7e", "active-1": "#f6bd60cc", "active-2": "#f6bd60cc", "active-line": SAND,
    "accent-soft": "#e6f3f1", "accent-line": "#2a9d8f59", "focus": TEAL, "focus-w": "2px", "focus-ring": "#2a9d8f26",
    "danger": "#c0392b", "warn": "#b7791f", "ok": "#1f9d55", "ok-text": "#1f7a45", "danger-text": "#c0392b", "warn-text": "#9a6416",
    "ok-soft": "#e3f3e9", "ok-line": "#1f9d5559", "danger-soft": "#fdf0ee", "danger-line": "#c0392b59",
    "warn-soft": "#fff6e5", "warn-line": SAND, "sidebar-bg": TEAL_DARK, "topbar-bg": "#fbf6eee6", "modal-bg": "#fbf6ee",
    "modal-border": "#c9dadd", "backdrop": "#0f1d2273", "toast-bg": TEAL_DARK, "toast-text": "#ffffff", "toast-line": TEAL_DARK,
    "toast-err-bg": "#c0392b", "toast-err-text": "#ffffff", "toast-err-line": "#c0392b", "badge-text": TEAL_DARK,
    "badge-bg": "#e6f3f1", "badge-line": "#c9dadd", "on-badge": "#ffffff", "bar-track": "#e6e1d6",
    "scroll-thumb": "#1d5f7440", "glow-1": "#2a9d8f40", "glow-2": "#f28c3833",
    "shadow-pop": "0 8px 24px #1d5f7426", "shadow-modal": "0 20px 60px #1d5f7440", "shadow-toast": "0 8px 24px #0000004d",
}
KLASIK_DARK = dict(KLASIK_LIGHT, **{
    "bg": "#111a1e", "bg-grid": "#7fd1c512", "panel": "#1b262cf0", "panel-solid": "#18242a", "panel-hover": "#22343a",
    "border": "#36494f", "border-strong": "#2a9d8f", "text": "#e2ebee", "muted": "#93a9b2", "label": "#7fd1c5",
    "nav-text": "#cfe6e8", "nav-title": "#7fb5b0", "accent": "#7fd1c5", "accent-2": TEAL, "on-accent": "#0b2229",
    "primary-1": TEAL, "primary-2": "#238a7e", "active-1": "#f6bd6099", "active-2": "#f6bd6099", "active-line": SAND,
    "accent-soft": "#1d3a3a", "accent-line": "#7fd1c559", "focus": "#7fd1c5", "focus-ring": "#7fd1c533",
    "danger": "#e57368", "warn": "#f6bd60", "ok": "#5cc28a", "ok-text": "#8fdcae", "danger-text": "#f3a59c", "warn-text": "#f6d08c",
    "ok-soft": "#1d3a2a", "ok-line": "#5cc28a59", "danger-soft": "#3a2220", "danger-line": "#e5736859",
    "warn-soft": "#33291a", "warn-line": "#8a6a2e", "sidebar-bg": "#0b2229", "topbar-bg": "#111a1ee6", "modal-bg": "#141f24",
    "modal-border": "#36494f", "backdrop": "#000000a6", "toast-bg": "#1d3a3a", "toast-text": "#e2ebee", "toast-line": "#2a9d8f",
    "toast-err-bg": "#3a2220", "toast-err-text": "#ffffff", "toast-err-line": "#e57368", "badge-text": "#7fd1c5",
    "badge-bg": "#1d3a3a", "badge-line": "#36494f", "on-badge": "#0b2229", "bar-track": "#2a3a40",
    "scroll-thumb": "#7fd1c540", "glow-1": "#2a9d8f26", "glow-2": "#f28c381a",
})
KLASIK_LABEL = {"tr": "Klasik (eski görünüm)", "en": "Classic (previous look)", "ar": "الكلاسيكي (المظهر السابق)"}


def register_klasik():
    style.register_scheme("klasik", dark=KLASIK_DARK, light=KLASIK_LIGHT, label=KLASIK_LABEL)


# ---------------------------------------------------------------- eski anahtar → token
_MAP = {"ink": "text", "muted": "muted", "title": "label", "card": "panel", "border": "border", "input": "panel-solid",
        "btn": "panel-solid", "hover": "panel-hover", "sel": "active-1", "badge": "accent-soft", "photobox": "panel-hover",
        "banner": "warn-soft", "bannerline": "warn-line", "dangerbg": "danger-soft", "bg": "bg"}


def color(key):
    """Seçili şemadaki renk (satır içi stiller için)."""
    return style.q(style.tok(_MAP.get(key, key)))


def resolve_dark(mode=None):
    return style.effective() == "dark"


def sync_dark():
    global DARK
    DARK = style.effective() == "dark"
    return DARK


def compat_qss():
    """Uygulamanın kendi nesne adları (2.1'deki theme.build_style ile aynı adlar) → şema tokenları."""
    T = {k: style.q(v) for k, v in style.scheme_tokens().items()
         if k not in ("border-w", "focus-w", "shadow-pop", "shadow-modal", "shadow-toast")}
    s = style.scale()

    def px(n):
        return "%dpx" % round(n * s)
    klasik = style.scheme() == "klasik"
    out = f"""
QFrame#Card {{ background: {T['panel']}; border: 1px solid {T['border']}; border-radius: 14px; }}
QLabel#PageTitle {{ font-size: {px(22)}; font-weight: 700; color: {T['text']}; }}
QLabel#SectionTitle {{ font-size: {px(15)}; font-weight: 600; color: {T['label']}; }}
QLabel#DetailName {{ font-size: {px(19)}; font-weight: 700; }}
QLabel#Muted {{ color: {T['muted']}; }}
QLabel#FieldName {{ color: {T['muted']}; font-size: {px(12.5)}; }}
QLabel#Badge {{ background: {T['accent-soft']}; color: {T['accent']}; border-radius: 9px; padding: 3px 9px; font-weight: 600; }}
QLabel#PhotoBox {{ background: {T['panel-hover']}; border-radius: 14px; color: {T['muted']}; }}
QListWidget#PhotoList {{ background: {T['panel-hover']}; border-radius: 12px; }}
QLabel#Banner {{ background: {T['warn-soft']}; color: {T['text']}; border: 1px solid {T['warn-line']}; border-radius: 12px; padding: 8px 12px; }}
QPushButton#Primary {{ color: {T['on-accent']}; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {T['primary-1']}, stop:1 {T['primary-2']}); border-color: transparent; font-weight: 600; }}
QPushButton#Primary:hover {{ border-color: {T['focus']}; }}
QPushButton#Primary:disabled {{ color: {T['muted']}; background: {T['panel-hover']}; }}
QPushButton#Danger {{ color: {T['danger-text']}; }}
QPushButton#Danger:hover {{ background: {T['danger-soft']}; border-color: {T['danger-line']}; }}
QPushButton#Round {{ min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; border-radius: 15px; font-weight: 700; }}
QPushButton#Tool {{ padding: 6px 12px; }}
QPushButton#Tool:checked {{ color: {T['on-accent']}; background: {T['accent']}; border-color: {T['accent']}; font-weight: 600; }}
QPushButton#Warn {{ color: {T['warn-text']}; border-color: {T['warn-line']}; }}
QPushButton#Warn:checked {{ color: #ffffff; background: {ORANGE}; border-color: {ORANGE}; }}
QLineEdit#Search {{ padding: 9px 16px; border-radius: 19px; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 2px; }}
QToolButton:hover:enabled {{ background: {T['panel-hover']}; }}
QTreeWidget::item {{ padding: 5px 2px; border-radius: 6px; }}
QTreeWidget::item:selected {{ background: {T['active-1']}; color: {T['text']}; }}
QTableWidget::item {{ padding: 4px; }}
QTabWidget QWidget {{ background: transparent; }}
QFrame#fcAgentCard {{ background: {T['panel']}; border: 1px solid {T['border']}; border-radius: 14px; padding: 10px 12px; }}
"""
    if klasik:
        # eski görünüm: koyu petrol yeşili kenar çubuğu, beyaz yazılar, kum rengi seçili sayfa
        out += f"""
QFrame#fcSidebar QLabel#fcBrandName {{ color: #ffffff; }}
QFrame#fcSidebar QLabel#fcBrandTag {{ color: #bfe0dc; }}
QFrame#fcSidebar QPushButton[fc~="nav-item"]:hover {{ background: #ffffff1a; color: #ffffff; }}
QFrame#fcSidebar QPushButton[fc~="nav-item"]:checked {{ color: #1d3b45; background: {SAND}; border-color: {SAND}; font-weight: 600; }}
QHeaderView::section {{ background: {'#0c1417' if DARK else '#2f3e46'}; color: #ffffff; }}
QToolTip {{ background: {TEAL_DARK}; color: #ffffff; border: 0; }}
"""
    return out
