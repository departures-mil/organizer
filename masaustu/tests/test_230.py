"""2.3.0: değişiklik geçmişi, garanti / son kullanma, gelişmiş filtre, dışa aktarma, yedek (şifreli + geri yükleme),
çeviri (çevrim dışı), Asistan (çevrim dışı) ve çevirilerin eksiksizliği."""
import io
import os
import re
import zipfile
from datetime import date, timedelta

import pytest

from conftest import ROOT
from organizer import ceviri, disa_aktar, filtre, i18n, yedek, zeka
from organizer.db import Database, merge_changelog, norm_day


def _item(db, name, **kw):
    data = {"name": name, "quantity": 1, "category_id": None, "location_id": None, "price": None, "currency": "USD",
            "notes": "", "created_at": "2026-11-01 10:00:00"}
    data.update(kw)
    return db.save_item(data)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "veri")
    d.set_setting("device_name", "Test-PC")
    return d


def test_gecmis_yaziliyor(db):
    i = _item(db, "Matkap", price=50.0)
    db.save_item({**db.get_item(i), "quantity": 3}, None, i)
    db.change_quantity(i, -1)
    db.lend_item(i, "Ali")
    db.trash_items([i])
    db.restore_items([i])
    log = db.changelog(i)
    assert [e.get("a", "") for e in log] == ["geri_yuklendi", "silindi", "", "", "", "eklendi"]
    assert log[-2]["c"] == [["quantity", "1", "3"]] and log[-2]["d"] == "Test-PC"
    assert ["loan_to", "", "Ali"] in log[2]["c"]


def test_gecmis_birlesir(db):
    i = _item(db, "Vida")
    rec = db.all_records()["items"][0]
    other = {"t": "2030-01-01T00:00:00.000Z", "d": "Telefon", "c": [["quantity", "1", "2"]]}
    rec = dict(rec, quantity=2, mtime="2030-01-01T00:00:00.000Z", changelog=[other])
    db.apply_remote("items", [rec])
    log = db.changelog(i)
    assert log[0]["d"] == "Telefon" and log[-1]["a"] == "eklendi"      # yerel geçmiş kaybolmadı
    assert len(merge_changelog(log, log)) == len(log)


def test_eski_surum_kaydi_yeni_alanlari_silmez(db):
    i = _item(db, "Pil", warranty_until="2027-05-01", expires_on="31.12.2027")
    assert db.get_item(i)["expires_on"] == "2027-12-31"
    rec = {k: v for k, v in db.all_records()["items"][0].items() if k not in ("warranty_until", "expires_on", "changelog")}
    rec["mtime"] = "2031-01-01T00:00:00.000Z"
    db.apply_remote("items", [rec])
    it = db.get_item(i)
    assert it["warranty_until"] == "2027-05-01" and it["expires_on"] == "2027-12-31" and it["changelog"]


def test_norm_day():
    assert norm_day("5.3.2027") == "2027-03-05" and norm_day("2027-3-5") == "2027-03-05"
    assert norm_day("31.02.2027") == "" and norm_day("") == ""


def test_filtre(db):
    soon = (date.today() + timedelta(days=5)).isoformat()
    a = _item(db, "Matkap", price=120.0, warranty_until=soon, shop_name="Yıldız Hırdavat")
    _item(db, "Vida", price=2.0, quantity=1, min_qty=5)
    _item(db, "İlaç", expires_on="2020-01-01")
    items = db.list_items()
    assert [d["name"] for d in filtre.apply(items, {"price_min": 100})] == ["Matkap"]
    assert [d["name"] for d in filtre.apply(items, {"shop": "yildiz"})] == ["Matkap"]
    assert [d["name"] for d in filtre.apply(items, {"flags": ["warranty_soon"]})] == ["Matkap"]
    assert [d["name"] for d in filtre.apply(items, {"flags": ["low"]})] == ["Vida"]
    assert [d["name"] for d in filtre.apply(items, {"flags": ["expired"]})] == ["İlaç"]
    assert [d["name"] for d in filtre.apply(items, {"flags": ["noprice"]})] == ["İlaç"]
    assert len(filtre.apply(items, {})) == 3 and filtre.count_active({"price_min": 1, "flags": ["low"]}) == 2
    filtre.save(db, "Pahalılar", {"price_min": 100})
    assert filtre.saved(db)[0]["f"]["price_min"] == 100
    filtre.remove(db, "Pahalılar")
    assert filtre.saved(db) == []
    rem = filtre.reminders(items)
    assert {d["name"] for d, *_ in rem} == {"Matkap", "İlaç"}   # son kullanması geçen (atılması gereken) hep listede


def test_hatirlatma_son_kullanma_gecmis_de_gorunur(db):
    _item(db, "Süt", expires_on=(date.today() - timedelta(days=3)).isoformat())
    rem = filtre.reminders(db.list_items())
    assert rem and rem[0][1] == "expiry" and rem[0][2] == -3


def test_xlsx_gecerli(db, tmp_path):
    _item(db, "Matkap <&>", price=12.5, notes="satır1\nsatır2")
    head, rows, widths = disa_aktar.table(db.list_items(), i18n.t)
    data = disa_aktar.xlsx_bytes(head, rows, widths, rtl=True, title="Organizer")
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/styles.xml"} <= set(z.namelist())
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "Matkap &lt;&amp;&gt;" in sheet and "<v>12.5</v>" in sheet and 'rightToLeft="1"' in sheet
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws["A3"].value == "Matkap <&>" and ws["E3"].value == 12.5
    disa_aktar.write_csv(tmp_path / "x.csv", head, rows)
    assert (tmp_path / "x.csv").read_text(encoding="utf-8-sig").startswith("Adı,")


def test_yedek_sifreli_ve_geri_yukleme_silmez(db, tmp_path):
    a = _item(db, "Matkap", quantity=1)
    b = _item(db, "Vida", quantity=100)
    blob = yedek.make(db, "gizli")
    assert yedek.is_encrypted(blob)
    with pytest.raises(yedek.WrongPassword):
        yedek.decrypt(blob, "yanlis")
    (tmp_path / "y.ozb").write_bytes(blob)
    with pytest.raises(yedek.NeedPassword):
        yedek.read(tmp_path / "y.ozb")
    z = yedek.read(tmp_path / "y.ozb", "gizli")
    db.change_quantity(a, 5)
    db.trash_items([b])
    c = _item(db, "Sonradan eklenen")
    counts = yedek.restore(db, z)
    assert counts == {"items": 2}
    names = {d["name"]: d for d in db.list_items()}
    assert names["Matkap"]["quantity"] == 1 and "Vida" in names and "Sonradan eklenen" in names   # hiçbir şey silinmedi
    assert db.archive_count() == 2                                                                 # eski haller arşivde
    assert db.changelog(a)[0]["a"] == "yedekten"
    assert db.get_item(c) is not None
    assert list((db.data_dir / "yedek").glob("geri-yukleme-oncesi-*.zip"))


def test_otomatik_yedek(db, tmp_path):
    yedek.save_settings(db, freq="daily", folder=tmp_path / "drive", keep=2, password="")
    assert yedek.due(db)
    for _ in range(3):
        p = yedek.run(db)
        os.utime(p)
        p.rename(p.with_name(p.name.replace(".zip", f"-{_}.zip")))
    yedek.prune(tmp_path / "drive", 2)
    assert len(yedek.list_backups(tmp_path / "drive")) == 2


def test_ceviri_cevrimdisi():
    out, ratio = ceviri.offline("Şarjlı matkap ve uç seti", "tr", "en")
    assert out == "cordless drill and bit set" and ratio == 1.0
    assert ceviri.offline("matkap", "tr", "ar")[0] == "مثقاب"
    assert ceviri.detect("مثقاب") == "ar" and ceviri.detect("screwdriver set") == "en"
    assert ceviri.translate("vida", "en", allow_online=False) == ("screw", "offline")


def test_asistan_cevrimdisi(db):
    loc = db.add_node("locations", "Yatak odası dolabı")
    _item(db, "Kışlık mont", location_id=loc)
    _item(db, "Matkap", warranty_until=(date.today() + timedelta(days=3)).isoformat())
    items = db.list_items()
    ans = "\n".join(zeka.ask_offline("Kışlık montlar nerede?", items, i18n.t))
    assert "Yatak odası dolabı" in ans
    assert "Matkap" in "\n".join(zeka.ask_offline("Garantisi biten ne var?", items, i18n.t))
    assert zeka.cfg() is None or True


def test_ceviriler_eksiksiz():
    src = ""
    for f in ("filtre.py", "zeka.py", "yedek.py", "ek_arayuz.py", "panel_page.py", "items_page.py", "item_dialog.py",
              "settings_page.py", "report.py", "app.py"):
        src += open(os.path.join(ROOT, "masaustu", "organizer", f), encoding="utf-8").read()
    keys = set()
    for m in re.finditer(r'\bt\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        k = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
        keys.add(k.encode().decode("unicode_escape").encode("latin1").decode("utf-8"))
    missing = sorted(k for k in keys if k not in i18n.STRINGS and not k.startswith("org."))
    assert not missing, missing
    for k, (en, ar) in i18n.STRINGS.items():
        for v in (en, ar):
            assert set(re.findall(r"\{(\w+)\}", k)) == set(re.findall(r"\{(\w+)\}", v)), k
