"""Yönetici e-postası depoda düz metin olarak durmaz; eski ortak projeden geçiş özetle çalışır (2.2.1)."""
import pathlib
import re

from organizer import cloud

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_eposta_duz_metin_yok():
    for p in list((ROOT / "masaustu" / "organizer").glob("*.py")) + list((ROOT / "telefon").glob("*.js")):
        assert not re.search(r"qa\d+@gmail\.com", p.read_text(encoding="utf-8")), p


class _Db(dict):
    def get_setting(self, k, d=None):
        return self.get(k, d)

    def set_setting(self, k, v):
        self[k] = v


def test_ortak_projeden_tasi_ozetle(monkeypatch):
    import hashlib
    monkeypatch.setattr(cloud, "_YONETICI_SHA256", hashlib.sha256(b"yonetici@example.com").hexdigest())
    db = _Db(fb_refresh="x", fb_email="  Yonetici@Example.com ")
    cloud.ortak_projeden_tasi(db)
    assert db.get("fb_config") == cloud._ESKI_ORTAK
    db = _Db(fb_refresh="x", fb_email="baska@example.com")
    cloud.ortak_projeden_tasi(db)
    assert not db.get("fb_config") and db.get("fb_ortak_kesildi") == "1"
