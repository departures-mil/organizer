"""Kullanım Limitleri — Python (PySide6) programları için ortak modül, v1.0.0.

Kullanıcının KENDİ Firebase hesabındaki günlük ücretsiz sınırı (okuma / yazma / silme) ve yapay zeka
kullanımını sayar; Ayarlar'a konacak bir kart (QWidget) verir. Ayrıntılar: kullanim.js ile aynı kurallar.

    import kullanim_sayac as KS
    KS.baslat(veri_klasoru, dil=lambda: 'tr', bulut=True, ai=False, proje=lambda: 'proje-id')
    KS.kaydet(method, url, govde_json_metni, http_durumu, yanit_json)   # her Firestore REST isteğinden sonra
    duzen.addWidget(KS.KullanimKarti())
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

SURUM = "1.0.0"
LIMIT = {"okuma": 50000, "yazma": 20000, "silme": 20000}
REHBER = "https://github.com/departures-mil/duyurular/blob/main/firebase-kurulum.md"

YAZI = {
    "tr": dict(baslik="Kullanım Limitleri", bulut="Bulut eşitleme (Firebase)", ai="Yapay zeka", okuma="Okuma",
               yazma="Yazma", silme="Silme", istek="İstek", token="Token", proje="Hesap / proje",
               yok="Bağlı bulut hesabı yok", sifir="Sınırların sıfırlanmasına", saat="sa", dk="dk", yerel="yerel saatle",
               doldu="Bugünkü ücretsiz sınır doldu. Eşitleme sıfırlanınca kendiliğinden devam eder.",
               aiDoldu="Yapay zeka hesabının sınırı doldu. Sıfırlanınca yeniden kullanılabilir.",
               not_="Bu cihazın bugünkü kullanımıdır. Sınırlar Firebase ücretsiz planının günlük sınırlarıdır; aynı hesaba bağlı diğer cihazlar da aynı sınırı paylaşır.",
               aiNot="Kendi yapay zeka anahtarınla yapılan bugünkü kullanım. Ücretsiz katmanın günlük sınırı modele göre değişir.",
               konsol="Firebase'de ayrıntılı gör", rehber="Kendi Firebase hesabınızı kurun (rehber)", dun="Dün",
               hic="Bu program sınırlı bir bulut ya da yapay zeka hizmeti kullanmıyor; kullanım sınırı yok. Güncellemeler GitHub'dan ücretsiz gelir."),
    "en": dict(baslik="Usage limits", bulut="Cloud sync (Firebase)", ai="AI", okuma="Reads", yazma="Writes",
               silme="Deletes", istek="Requests", token="Tokens", proje="Account / project",
               yok="No cloud account connected", sifir="Limits reset in", saat="h", dk="min", yerel="local time",
               doldu="Today's free limit is used up. Sync resumes automatically after the reset.",
               aiDoldu="Your AI account limit is reached. It can be used again after the reset.",
               not_="Usage by this device today. Limits are the daily limits of the Firebase free plan; other devices on the same account share them.",
               aiNot="Today's usage with your own AI key. The free tier's daily limit depends on the model.",
               konsol="View details in Firebase", rehber="Set up your own Firebase account (guide)", dun="Yesterday",
               hic="This program uses no limited cloud or AI service, so there is no usage limit. Updates come free from GitHub."),
    "ar": dict(baslik="حدود الاستخدام", bulut="المزامنة السحابية (Firebase)", ai="الذكاء الاصطناعي", okuma="قراءة",
               yazma="كتابة", silme="حذف", istek="طلبات", token="رموز", proje="الحساب / المشروع",
               yok="لا يوجد حساب سحابي مرتبط", sifir="تُعاد الحدود بعد", saat="س", dk="د", yerel="بالتوقيت المحلي",
               doldu="انتهى الحد المجاني لهذا اليوم. ستستأنف المزامنة تلقائياً بعد إعادة التعيين.",
               aiDoldu="بلغ حساب الذكاء الاصطناعي حده. يمكن استخدامه مجدداً بعد إعادة التعيين.",
               not_="استخدام هذا الجهاز اليوم. الحدود هي الحدود اليومية لخطة Firebase المجانية، وتتشاركها الأجهزة الأخرى على الحساب نفسه.",
               aiNot="استخدام اليوم بمفتاح الذكاء الاصطناعي الخاص بك. يختلف الحد اليومي للطبقة المجانية حسب النموذج.",
               konsol="عرض التفاصيل في Firebase", rehber="أنشئ حساب Firebase الخاص بك (دليل)", dun="أمس",
               hic="لا يستخدم هذا البرنامج خدمة سحابية أو ذكاءً اصطناعياً محدوداً، لذا لا يوجد حد للاستخدام. تصل التحديثات مجاناً من GitHub."),
}

_A = {"dosya": None, "dil": None, "bulut": True, "ai": False, "proje": None}
_kilit = threading.Lock()
_dinleyiciler = []


def _pasifik_simdi():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        # PDT/PST yaklaşık: Mart 2. Pazar - Kasım 1. Pazar arası -7, diğer -8
        u = datetime.now(timezone.utc)
        yil = u.year
        mart = datetime(yil, 3, 8, 10, tzinfo=timezone.utc)
        mart += timedelta(days=(6 - mart.weekday()) % 7)
        kasim = datetime(yil, 11, 1, 9, tzinfo=timezone.utc)
        kasim += timedelta(days=(6 - kasim.weekday()) % 7)
        return u + timedelta(hours=-7 if mart <= u < kasim else -8)


def bugun():
    return _pasifik_simdi().strftime("%Y-%m-%d")


def sifirlanmaya_sn():
    p = _pasifik_simdi()
    return max(0, 86400 - (p.hour * 3600 + p.minute * 60 + p.second))


def _bos(gun):
    return dict(gun=gun, okuma=0, yazma=0, silme=0, aiIstek=0, aiToken=0, bulutDoldu=0, aiDoldu=0)


def _oku():
    try:
        with open(_A["dosya"], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _yaz(v):
    try:
        tmp = _A["dosya"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(v, f)
        os.replace(tmp, _A["dosya"])
    except Exception:
        pass


def veri():
    if not _A["dosya"]:
        return {"bugun": _bos(bugun())}
    with _kilit:
        v = _oku() or {}
        gun = bugun()
        if not v.get("bugun") or v["bugun"].get("gun") != gun:
            if v.get("bugun"):
                v["dun"] = v["bugun"]
            v["bugun"] = _bos(gun)
            _yaz(v)
        return v


def ekle(delta):
    if not delta or not _A["dosya"]:
        return
    v = veri()
    with _kilit:
        b = v["bugun"]
        for k in ("okuma", "yazma", "silme", "aiIstek", "aiToken"):
            n = int(delta.get(k) or 0)
            if n > 0:
                b[k] = b.get(k, 0) + n
        if delta.get("bulutDoldu"):
            b["bulutDoldu"] = int(time.time() * 1000)
        if delta.get("aiDoldu"):
            b["aiDoldu"] = int(time.time() * 1000)
        if delta.get("proje"):
            v["proje"] = delta["proje"]
        _yaz(v)
    for f in list(_dinleyiciler):
        try:
            f()
        except Exception:
            pass


def _json(s):
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s if isinstance(s, str) else s.decode("utf-8", "ignore"))
    except Exception:
        return None


def _kota(status, govde):
    return status == 429 or bool(re.search(r"RESOURCE_EXHAUSTED|quota exceeded|insufficient_quota|rate_limit",
                                           str(govde or ""), re.I))


def cozumle(method, url, govde, status, yanit):
    url = str(url or "")
    method = str(method or "GET").upper()
    if "firestore.googleapis.com" in url:
        d = {}
        yol = url.split("?")[0]
        if _kota(status, yanit if isinstance(yanit, str) else json.dumps(yanit or "", ensure_ascii=False)):
            return {"bulutDoldu": 1}
        b, y = _json(govde), _json(yanit)
        if re.search(r":(commit|batchWrite)$", yol):
            for w in (b or {}).get("writes", []) or []:
                if isinstance(w, dict) and w.get("delete"):
                    d["silme"] = d.get("silme", 0) + 1
                else:
                    d["yazma"] = d.get("yazma", 0) + 1
            return d
        if re.search(r":(runQuery|runAggregationQuery)$", yol):
            n = sum(1 for x in (y or []) if isinstance(x, dict) and x.get("document")) if isinstance(y, list) else 0
            return {"okuma": max(1, n)}
        if yol.endswith(":batchGet"):
            n = sum(1 for x in (y or []) if isinstance(x, dict) and (x.get("found") or x.get("missing"))) if isinstance(y, list) else 0
            return {"okuma": max(1, n)}
        if re.search(r":(beginTransaction|rollback|listen|write)$", yol):
            return d
        parca = yol.split("/documents", 1)[1] if "/documents" in yol else ""
        seg = len([p for p in parca.split("/") if p])
        if method == "GET":
            d["okuma"] = max(1, len((y or {}).get("documents", []) or [])) if seg % 2 == 1 and isinstance(y, dict) else 1
        elif method == "DELETE":
            d["silme"] = 1
        elif method in ("PATCH", "POST", "PUT"):
            d["yazma"] = 1
        return d
    if re.search(r"generativelanguage\.googleapis\.com|api\.openai\.com|api\.anthropic\.com|aiplatform\.googleapis\.com", url):
        d = {"aiIstek": 1}
        if _kota(status, yanit if isinstance(yanit, str) else json.dumps(yanit or "")):
            d["aiDoldu"] = 1
            return d
        y = _json(yanit)
        if isinstance(y, list) and y:
            y = y[-1]
        if isinstance(y, dict):
            if y.get("usageMetadata"):
                d["aiToken"] = int(y["usageMetadata"].get("totalTokenCount") or 0)
            elif y.get("usage"):
                u = y["usage"]
                d["aiToken"] = int(u.get("total_tokens") or 0) or int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
        return d
    return None


def kaydet(method, url, govde, status, yanit):
    """Bir HTTP isteğinden sonra çağrılır; hiçbir zaman hata fırlatmaz."""
    try:
        d = cozumle(method, url, govde, status, yanit)
        m = re.search(r"/projects/([^/]+)/", str(url))
        if d is not None and m and "firestore" in str(url) and (status or 0) < 400:
            d["proje"] = m.group(1)
        ekle(d)
    except Exception:
        pass


def kota_doldu(hangi="bulut"):
    ekle({"aiDoldu": 1} if hangi == "ai" else {"bulutDoldu": 1})


def baslat(veri_klasoru, dil=None, bulut=True, ai=False, proje=None):
    try:
        os.makedirs(veri_klasoru, exist_ok=True)
    except Exception:
        pass
    _A.update(dosya=os.path.join(veri_klasoru, "kullanim-limit.json"), dil=dil, bulut=bulut, ai=ai, proje=proje)


def _dil():
    try:
        d = _A["dil"]() if callable(_A["dil"]) else _A["dil"]
    except Exception:
        d = None
    d = str(d or "tr")[:2].lower()
    return d if d in YAZI else "tr"


def T(k):
    return YAZI[_dil()][k]


def _proje():
    try:
        p = (_A["proje"]() if callable(_A["proje"]) else _A["proje"]) or ""
    except Exception:
        p = ""
    return p or veri().get("proje") or ""


def _sayi(n):
    return f"{int(n):,}".replace(",", ".")


def _sure(sn):
    dk = -(-sn // 60)
    s = dk // 60
    return (f"{s} {T('saat')} " if s else "") + f"{dk % 60} {T('dk')}"


def html_ozet():
    """Kartın içeriğini zengin metin (Qt HTML) olarak üretir."""
    v = veri()
    b = v["bugun"]
    import html as _h
    e = _h.escape
    p = []

    def cubuk(ad, n, lim):
        y = min(100.0, n * 100.0 / lim)
        renk = "#e5484d" if y >= 100 else "#e2a400" if y >= 80 else "#22a06b"
        dolu = max(1, int(round(y * 2)))
        return (f"<tr><td>{e(T(ad))}</td><td align='right'><b>{_sayi(n)} / {_sayi(lim)} (%{int(y)})</b></td></tr>"
                f"<tr><td colspan='2'><table cellspacing='0' cellpadding='0' width='100%' style='background:#8883'><tr>"
                f"<td width='{dolu}' style='background:{renk}' height='7'></td><td></td></tr></table></td></tr>")

    if _A["bulut"]:
        p.append(f"<p><b>☁ {e(T('bulut'))}</b></p>")
        p.append(f"<table width='100%' cellspacing='0' cellpadding='2'><tr><td>{e(T('proje'))}</td>"
                 f"<td align='right'><b>{e(_proje() or T('yok'))}</b></td></tr>")
        p.append(cubuk("okuma", b["okuma"], LIMIT["okuma"]) + cubuk("yazma", b["yazma"], LIMIT["yazma"])
                 + cubuk("silme", b["silme"], LIMIT["silme"]) + "</table>")
        if b.get("bulutDoldu"):
            p.append(f"<p style='color:#e5484d'><b>{e(T('doldu'))}</b></p>")
        if v.get("dun"):
            d = v["dun"]
            p.append(f"<p style='color:gray'>{e(T('dun'))}: {e(T('okuma'))} {_sayi(d.get('okuma', 0))} · "
                     f"{e(T('yazma'))} {_sayi(d.get('yazma', 0))} · {e(T('silme'))} {_sayi(d.get('silme', 0))}</p>")
        p.append(f"<p style='color:gray'>{e(T('not_'))}</p>")
    if _A["ai"]:
        p.append(f"<p><b>✦ {e(T('ai'))}</b></p>")
        if b.get("aiDoldu"):
            p.append(f"<p style='color:#e5484d'><b>{e(T('aiDoldu'))}</b></p>")
        p.append(f"<table width='100%'><tr><td>{e(T('istek'))}</td><td align='right'><b>{_sayi(b['aiIstek'])}</b></td></tr>"
                 f"<tr><td>{e(T('token'))}</td><td align='right'><b>{_sayi(b['aiToken'])}</b></td></tr></table>")
        p.append(f"<p style='color:gray'>{e(T('aiNot'))}</p>")
    if not _A["bulut"] and not _A["ai"]:
        return f"<p>✓ {e(T('hic'))}</p>"
    sn = sifirlanmaya_sn()
    saat = (datetime.now() + timedelta(seconds=sn)).strftime("%H:%M")
    p.append(f"<p>⏱ {e(T('sifir'))}: <b>{e(_sure(sn))}</b> ({saat} {e(T('yerel'))})</p>")
    return "".join(p)


def KullanimKarti(parent=None):
    """Ayarlar sayfasına eklenecek kart (PySide6). Kendi kendini 30 sn'de bir günceller."""
    from PySide6.QtCore import QTimer, Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QHBoxLayout, QWidget

    kutu = QFrame(parent)
    kutu.setObjectName("kullanimKarti")
    kutu.setStyleSheet("#kullanimKarti{border:1px solid rgba(127,127,127,90);border-radius:10px;}")
    dis = QVBoxLayout(kutu)
    dis.setContentsMargins(14, 12, 14, 12)
    govde = QWidget()
    dis.addWidget(govde)
    alt = QHBoxLayout()
    dugme = QPushButton()
    rehber = QPushButton()
    rehber.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REHBER)))
    alt.addWidget(dugme)
    alt.addWidget(rehber)
    alt.addStretch(1)
    dis.addLayout(alt)

    def ac():
        p = _proje()
        if p:
            QDesktopServices.openUrl(QUrl(f"https://console.firebase.google.com/project/{p}/firestore/usage"))

    dugme.clicked.connect(ac)

    def etiket(metin, stil="", sar=True):
        l = QLabel(metin)
        l.setWordWrap(sar)
        if stil:
            l.setStyleSheet(stil)
        return l

    def yenile():
        nonlocal govde
        try:
            v = veri()
            b = v["bugun"]
            yeni = QWidget()
            dz = QVBoxLayout(yeni)
            dz.setContentsMargins(0, 0, 0, 0)
            dz.setSpacing(5)
            dz.addWidget(etiket(T("baslik").upper(), "font-weight:600;letter-spacing:1px;"))
            if not _A["bulut"] and not _A["ai"]:
                dz.addWidget(etiket("✓ " + T("hic")))
            if _A["bulut"]:
                dz.addWidget(etiket("☁ " + T("bulut"), "font-weight:600;margin-top:4px;"))
                g = QGridLayout()
                g.setHorizontalSpacing(10)
                g.addWidget(etiket(T("proje"), sar=False), 0, 0)
                pl = etiket(_proje() or T("yok"), "font-weight:600;", sar=False)
                pl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                g.addWidget(pl, 0, 1)
                satir = 1
                for ad in ("okuma", "yazma", "silme"):
                    n, lim = int(b.get(ad, 0)), LIMIT[ad]
                    y = min(100.0, n * 100.0 / lim)
                    renk = "#e5484d" if y >= 100 else "#e2a400" if y >= 80 else "#22a06b"
                    g.addWidget(etiket(T(ad), sar=False), satir, 0)
                    d = etiket(f"{_sayi(n)} / {_sayi(lim)} (%{int(y)})", "font-weight:600;", sar=False)
                    d.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    g.addWidget(d, satir, 1)
                    cb = QProgressBar()
                    cb.setRange(0, 1000)
                    cb.setValue(int(y * 10))
                    cb.setTextVisible(False)
                    cb.setFixedHeight(8)
                    cb.setStyleSheet("QProgressBar{border:0;border-radius:4px;background:rgba(127,127,127,60);}"
                                     f"QProgressBar::chunk{{border-radius:4px;background:{renk};}}")
                    g.addWidget(cb, satir + 1, 0, 1, 2)
                    satir += 2
                dz.addLayout(g)
                if b.get("bulutDoldu"):
                    dz.addWidget(etiket(T("doldu"), "color:#e5484d;font-weight:600;"))
                if v.get("dun"):
                    d0 = v["dun"]
                    dz.addWidget(etiket(f"{T('dun')}: {T('okuma')} {_sayi(d0.get('okuma', 0))} · {T('yazma')} "
                                        f"{_sayi(d0.get('yazma', 0))} · {T('silme')} {_sayi(d0.get('silme', 0))}", "color:gray;"))
                dz.addWidget(etiket(T("not_"), "color:gray;"))
            if _A["ai"]:
                dz.addWidget(etiket("✦ " + T("ai"), "font-weight:600;margin-top:4px;"))
                if b.get("aiDoldu"):
                    dz.addWidget(etiket(T("aiDoldu"), "color:#e5484d;font-weight:600;"))
                g2 = QGridLayout()
                for i, (ad, k) in enumerate((("istek", "aiIstek"), ("token", "aiToken"))):
                    g2.addWidget(etiket(T(ad), sar=False), i, 0)
                    d = etiket(_sayi(b.get(k, 0)), "font-weight:600;", sar=False)
                    d.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    g2.addWidget(d, i, 1)
                dz.addLayout(g2)
                dz.addWidget(etiket(T("aiNot"), "color:gray;"))
            if _A["bulut"] or _A["ai"]:
                sn = sifirlanmaya_sn()
                saat = (datetime.now() + timedelta(seconds=sn)).strftime("%H:%M")
                dz.addWidget(etiket(f"⏱ {T('sifir')}: <b>{_sure(sn)}</b> ({saat} {T('yerel')})"))
            dis.replaceWidget(govde, yeni)
            govde.deleteLater()
            govde = yeni
            kutu.setLayoutDirection(Qt.RightToLeft if _dil() == "ar" else Qt.LeftToRight)
            dugme.setText(T("konsol"))
            dugme.setVisible(bool(_A["bulut"] and _proje()))
            rehber.setText(T("rehber"))
            rehber.setVisible(bool(_A["bulut"]))
        except RuntimeError:
            pass

    yenile()
    zaman = QTimer(kutu)
    zaman.timeout.connect(yenile)
    zaman.start(30000)
    kutu.yenile = yenile
    return kutu
