"""Sürüm tek kaynaktan: masaüstü, telefon ve Android aynı semver; eski karşılaştırmalar yeni sürümü "daha yeni" görür."""
import json
import os
import re

from conftest import ROOT
from organizer import __version__, goster


def test_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert goster() == "v" + __version__
    assert goster("2.1.0.12") == "v.1.0.12"


def test_telefon_ayni_surum():
    js = open(os.path.join(ROOT, "telefon", "app.js"), encoding="utf-8").read()
    assert re.search(r'APP_VERSION = "([^"]+)"', js).group(1) == __version__


def test_release_notes():
    n = json.load(open(os.path.join(ROOT, "release-notes.json"), encoding="utf-8"))
    assert set(n) >= {"tr", "en", "ar"} and all(n[k].strip() for k in ("tr", "en", "ar"))


def test_eski_karsilastirma_yeni_gorur():
    """2.1.0.x güncelleyicileri (masaüstü updater.vkey, telefon Updater.newer, Java Ota.newer) sayıları sırayla karşılaştırır."""
    def vkey(v):
        return tuple(int(x) for x in re.findall(r"\d+", v))
    assert vkey(__version__) > vkey("2.1.0.13")
    from fccore.updater import cmp
    assert cmp(__version__, "2.1.0") > 0


def test_android_surum_kodu():
    sh = open(os.path.join(ROOT, "android", "build.sh"), encoding="utf-8").read()
    assert "versionCode" in sh or "VERSION_CODE" in sh
    a, b, c = (int(x) for x in __version__.split("."))
    assert a * 10000 + b * 100 + c > 20111      # kurulu en eski APK'nın versionCode'u (v.1.0.11)


def test_cekirdek_version_dosyasi():
    v = open(os.path.join(ROOT, "cekirdek", "VERSION"), encoding="utf-8").read()
    assert "ortak-cekirdek" in v and re.search(r"\b[0-9a-f]{7,40}\b", v)
