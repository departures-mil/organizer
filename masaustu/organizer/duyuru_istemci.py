"""Admin Duyuruları istemcisi (PySide6) v1.0.0 — bütün Python/Qt programları için ortak.

Kullanım (ana pencere kurulduktan sonra):
    import duyuru_istemci
    self.duyuru = duyuru_istemci.DuyuruIstemci(self, "bereket-defter", APP_VERSION, dil=i18n.lang,
                                               guncelle=self.open_update)
    satir.addWidget(self.duyuru.dugme)     # 🔔 düğmesi (okunmamış sayısıyla)

Kaynak: https://raw.githubusercontent.com/departures-mil/duyurular/main/duyurular.json
Yeni duyuru bir kez pencere olarak açılır; görülenler QSettings'te tutulur. İnternet yoksa son liste gösterilir.
"""
import json
import threading
import time
import urllib.request
from datetime import datetime

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

KAYNAK = "https://raw.githubusercontent.com/departures-mil/duyurular/main/duyurular.json"
YAZI = {
    "tr": {"baslik": "Duyurular", "tamam": "Tamam", "kapat": "Kapat", "yok": "Henüz duyuru yok.",
           "ac": "Bağlantıyı aç", "guncelle": "Şimdi güncelle", "onemli": "Önemli"},
    "en": {"baslik": "Announcements", "tamam": "OK", "kapat": "Close", "yok": "No announcements yet.",
           "ac": "Open link", "guncelle": "Update now", "onemli": "Important"},
    "ar": {"baslik": "الإعلانات", "tamam": "حسناً", "kapat": "إغلاق", "yok": "لا توجد إعلانات بعد.",
           "ac": "فتح الرابط", "guncelle": "حدّث الآن", "onemli": "مهم"},
}


def _surum_karsilastir(a, b):
    def p(v):
        return [int(x) if x.isdigit() else 0 for x in str(v).lstrip("vV.").split(".")]
    x, y = p(a), p(b)
    n = max(len(x), len(y))
    x += [0] * (n - len(x))
    y += [0] * (n - len(y))
    return (x > y) - (x < y)


def _zaman(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class DuyuruIstemci(QObject):
    _geldi = Signal(list)

    def __init__(self, pencere, uygulama, surum, dil=None, guncelle=None, aralik_dk=30):
        super().__init__(pencere)
        self.pencere, self.uygulama, self.surum = pencere, uygulama, str(surum)
        self._dil, self._guncelle = dil, guncelle
        self.ayar = QSettings("AdminDuyuru", uygulama)
        self.liste, self.kuyruk, self.acik = [], [], False
        self.dugme = QPushButton("🔔")
        self.dugme.setObjectName("light")
        self.dugme.setStyleSheet("padding:6px 10px;")
        self.dugme.setCursor(Qt.PointingHandCursor)
        self.dugme.clicked.connect(self.listeyi_goster)
        self.dugme.hide()
        self._geldi.connect(self._isle)
        try:
            self._isle(json.loads(self.ayar.value("onbellek", "[]") or "[]"), ac=False)
        except Exception:
            pass
        QTimer.singleShot(5000, self.yenile)
        self.zamanlayici = QTimer(self)
        self.zamanlayici.timeout.connect(self.yenile)
        self.zamanlayici.start(max(5, aralik_dk) * 60000)

    # --- yardımcılar
    def dil(self):
        try:
            d = self._dil() if callable(self._dil) else self._dil
        except Exception:
            d = None
        d = str(d or "tr")[:2].lower()
        return d if d in YAZI else "tr"

    def T(self, k):
        return YAZI[self.dil()][k]

    def sec(self, o):
        if not o:
            return ""
        if isinstance(o, str):
            return o
        return o.get(self.dil()) or o.get("tr") or o.get("en") or o.get("ar") or ""

    def gorulen(self):
        try:
            return json.loads(self.ayar.value("gorulen", "[]") or "[]")
        except Exception:
            return []

    def goruldu(self, did):
        g = self.gorulen()
        if did not in g:
            g.append(did)
            self.ayar.setValue("gorulen", json.dumps(g[-300:]))

    def uygun(self, d):
        if not isinstance(d, dict) or not d.get("id") or d.get("aktif") is False:
            return False
        h = d.get("hedef") or ["*"]
        if "*" not in h and self.uygulama not in h:
            return False
        simdi = time.time()
        b, s = _zaman(d.get("baslangic")), _zaman(d.get("bitis"))
        if b and b > simdi or s and s < simdi:
            return False
        if d.get("altSurum") and _surum_karsilastir(self.surum, d["altSurum"]) < 0:
            return False
        if d.get("ustSurum") and _surum_karsilastir(self.surum, d["ustSurum"]) > 0:
            return False
        return True

    # --- indirme (arka planda)
    def yenile(self):
        def is_():
            try:
                req = urllib.request.Request(f"{KAYNAK}?t={int(time.time() // 60)}",
                                             headers={"User-Agent": "AdminDuyuru", "Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    t = (json.loads(r.read().decode("utf-8")) or {}).get("duyurular") or []
                self._geldi.emit(t)
            except Exception:
                pass
        threading.Thread(target=is_, daemon=True).start()

    def _isle(self, t, ac=True):
        if ac:
            self.ayar.setValue("onbellek", json.dumps(t, ensure_ascii=False))
        self.liste = sorted([d for d in t if self.uygun(d)], key=lambda d: str(d.get("tarih")), reverse=True)
        g = self.gorulen()
        for d in reversed(self.liste):
            if d["id"] not in g and all(k["id"] != d["id"] for k in self.kuyruk):
                self.kuyruk.append(d)
        self._dugme_guncelle()
        if ac:
            QTimer.singleShot(300, self._siradaki)

    def _dugme_guncelle(self):
        g = self.gorulen()
        yeni = sum(1 for d in self.liste if d["id"] not in g)
        self.dugme.setText("🔔" + (f" {yeni}" if yeni else ""))
        self.dugme.setToolTip(self.T("baslik"))
        self.dugme.setStyleSheet("padding:6px 10px;" + ("background:#dc2626;color:white;font-weight:700;" if yeni else ""))
        self.dugme.setVisible(bool(self.liste))

    # --- pencereler
    def _govde(self, d):
        import html as _h
        try:
            tr = datetime.fromisoformat(str(d.get("tarih")).replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y")
        except Exception:
            tr = ""
        et = f'<span style="background:#dc2626;color:white;border-radius:4px;padding:0 6px;">{self.T("onemli")}</span> ' \
            if d.get("onem") == "onemli" else ""
        metin = _h.escape(self.sec(d.get("metin"))).replace("\n", "<br>")
        return (f'<h3 style="margin:0">{et}{_h.escape(self.sec(d.get("baslik")))}</h3>'
                f'<div style="color:#6b7280;font-size:12px;margin:2px 0 8px">{tr}</div><div style="font-size:14px">{metin}</div>')

    def _pencere(self, govde_html, dugmeler):
        dlg = QDialog(self.pencere)
        dlg.setWindowTitle("🔔 " + self.T("baslik"))
        dlg.setLayoutDirection(Qt.RightToLeft if self.dil() == "ar" else Qt.LeftToRight)
        dlg.setMinimumWidth(480)
        v = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(f'<div dir="{"rtl" if self.dil() == "ar" else "ltr"}">{govde_html}</div>')
        tb.setMinimumHeight(220)
        v.addWidget(tb)
        h = QHBoxLayout()
        h.addStretch()
        for yazi, ana, is_ in dugmeler:
            b = QPushButton(yazi)
            if ana:
                b.setDefault(True)
            b.clicked.connect(lambda _=False, f=is_: (dlg.accept(), f and f()))
            h.addWidget(b)
        v.addLayout(h)
        dlg.exec()

    def _siradaki(self):
        if self.acik or not self.kuyruk:
            return
        d = self.kuyruk.pop(0)
        self.acik = True
        self.goruldu(d["id"])
        dugmeler = []
        if d.get("guncellemeDugmesi") and callable(self._guncelle):
            dugmeler.append((self.T("guncelle"), False, self._guncelle))
        if d.get("link"):
            dugmeler.append((self.T("ac"), False, lambda u=d["link"]: QDesktopServices.openUrl(QUrl(u))))
        dugmeler.append((self.T("tamam"), True, None))
        try:
            self._pencere(self._govde(d), dugmeler)
        finally:
            self.acik = False
            self._dugme_guncelle()
            QTimer.singleShot(300, self._siradaki)

    def listeyi_goster(self):
        if self.liste:
            parca = []
            for d in self.liste:
                link = f'<div><a href="{d["link"]}">{self.T("ac")}</a></div>' if d.get("link") else ""
                parca.append(self._govde(d) + link)
            icerik = '<hr style="border:0;border-top:1px solid #ddd">'.join(parca)
        else:
            icerik = f"<p>{self.T('yok')}</p>"
        for d in self.liste:
            self.goruldu(d["id"])
        self._dugme_guncelle()
        self._pencere(icerik, [(self.T("kapat"), True, None)])
