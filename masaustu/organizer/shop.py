"""Eşyanın satın alındığı yer (1.4.0): dükkan adı, yeri, iletişim numarası ve numaranın çalıştığı uygulamalar.

Formda numaranın yanında WhatsApp ve Telegram düğmeleri vardır; tıklayınca açılır/kapanır (renkli = bu
numara o uygulamada çalışıyor, soluk = çalışmıyor) ve altında hangisinin çalıştığı yazılır.
Listede ve ayrıntı panelinde renkli simgeye tıklayınca o uygulamada sohbet açılır.
"""
from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QToolTip, QWidget

from .db import phone_for_links
from .i18n import t
from .paths import asset

# (alan, simge dosyası, görünen ad)
SHOP_CHANNELS = [("shop_whatsapp", "whatsapp", "WhatsApp"), ("shop_telegram", "telegram", "Telegram")]
GREEN = "#1f9d55"
GREY = "#9aa5ab"


def _icon(key):
    return QIcon(asset(f"{key}.png"))


def _gray(key, size):
    return _icon(key).pixmap(QSize(size, size), QIcon.Disabled)


def channel_url(key, phone, country_code):
    digits = phone_for_links(phone, country_code)
    if not digits:
        return ""
    return {"whatsapp": f"https://wa.me/{digits}", "telegram": f"https://t.me/+{digits}"}[key]


def open_shop_channel(key, phone, country_code, anchor=None):
    url = channel_url(key, phone, country_code)
    if not url:
        return
    if anchor is not None:
        name = dict((k, n) for _, k, n in SHOP_CHANNELS)[key]
        QToolTip.showText(anchor.mapToGlobal(anchor.rect().bottomLeft()), t("{app} açılıyor…", app=name), anchor)
    QDesktopServices.openUrl(QUrl(url))


def has_shop(d):
    return bool((d.get("shop_name") or "").strip() or (d.get("shop_place") or "").strip()
                or (d.get("shop_phone") or "").strip())


def shop_title(d):
    return (d.get("shop_name") or "").strip() or (d.get("shop_place") or "").strip() or (d.get("shop_phone") or "").strip()


def shop_tooltip(d):
    rows = []
    if d.get("shop_name"):
        rows.append(t("Dükkan: {x}", x=d["shop_name"]))
    if d.get("shop_place"):
        rows.append(t("Yeri: {x}", x=d["shop_place"]))
    if d.get("shop_phone"):
        rows.append(t("Numara: {x}", x=d["shop_phone"]))
    apps = [n for f, _, n in SHOP_CHANNELS if d.get(f)]
    if d.get("shop_phone"):
        rows.append(t("Çalışan: {x}", x=", ".join(apps)) if apps else t("WhatsApp / Telegram işaretlenmemiş"))
    return "\n".join(rows)


class ChannelToggle(QToolButton):
    """Formdaki WhatsApp / Telegram düğmesi: tıklayınca etkin olur (renkli, yeşil çerçeve), yeniden tıklayınca kapanır."""

    def __init__(self, key, label, parent=None):
        super().__init__(parent)
        self.key, self.label = key, label
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(26, 26))
        self.setMinimumHeight(40)
        self.toggled.connect(self._draw)
        self._draw(False)

    def _draw(self, on):
        self.setIcon(_icon(self.key) if on else QIcon(_gray(self.key, 26)))
        self.setText(("✓ " if on else "") + self.label)
        self.setToolTip(t("{app} bu numarada çalışıyor. Kapatmak için tıklayın.", app=self.label) if on
                        else t("{app} bu numarada çalışıyorsa tıklayıp etkinleştirin.", app=self.label))
        self.setStyleSheet(
            f"QToolButton {{ border: 2px solid {GREEN if on else '#d5dbde'}; border-radius: 10px; padding: 4px 12px;"
            f" background: {'#e8f7ee' if on else 'white'}; color: {GREEN if on else GREY}; font-weight: 700; }}")


class ChannelPicker(QWidget):
    """Numara kutusunun yanındaki iki düğme + altında durum yazısı."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.buttons = {}
        for field, key, label in SHOP_CHANNELS:
            b = ChannelToggle(key, label)
            b.toggled.connect(lambda *_: self.changed.emit())
            self.buttons[field] = b
            lay.addWidget(b)

    def values(self):
        return {f: int(b.isChecked()) for f, b in self.buttons.items()}

    def set_values(self, d):
        for f, b in self.buttons.items():
            b.setChecked(bool(d.get(f)))

    def status_text(self, phone):
        on = [n for f, _, n in SHOP_CHANNELS if self.buttons[f].isChecked()]
        if not on:
            return t("Bu numara için WhatsApp / Telegram seçilmedi. Çalışanın düğmesine tıklayın.")
        text = t("Bu numarada çalışan: {x}", x=" + ".join(on))
        if not phone.strip():
            text += "  " + t("(numara yazılmadı)")
        return "✓ " + text


class ShopLinks(QWidget):
    """Listede / ayrıntıda: dükkan adı + etkin uygulamaların renkli simgeleri (tıklayınca sohbet açılır)."""

    def __init__(self, d, country_code, show_text=True, icon=24, parent=None, name_only=False):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(4)
        tip = shop_tooltip(d)
        if show_text:
            # name_only: adres ayrı sütunda gösterildiği için burada yalnızca ad (yoksa numara)
            txt = ((d.get("shop_name") or "").strip() or (d.get("shop_phone") or "").strip()) if name_only else shop_title(d)
            lbl = QLabel(txt or "—")
            lbl.setToolTip(tip)
            lbl.setStyleSheet("background: transparent;")
            lay.addWidget(lbl, 1)
        phone = d.get("shop_phone") or ""
        for field, key, label in SHOP_CHANNELS:
            if not d.get(field) or not phone.strip():
                continue
            b = QToolButton()
            b.setIcon(_icon(key))
            b.setIconSize(QSize(icon, icon))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(t("{app} ile yaz: {p}", app=label, p=phone))
            b.clicked.connect(lambda _=False, k=key, w=b: open_shop_channel(k, phone, country_code, w))
            lay.addWidget(b)
        if not show_text:
            lay.addStretch()
        self.setToolTip(tip)
