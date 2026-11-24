"""Eşitleme kuralı: hiçbir kayıt kalıcı silinmez — uzak silme → arşiv, çakışma → yedek; geri alınabilir."""
from organizer.db import Database


def _item(db, name="Matkap"):
    loc = db.tree_ordered("locations")[0][0]
    return db.save_item({"name": name, "quantity": 1, "location_id": loc, "category_id": None, "price": 10.0,
                         "currency": "TRY", "notes": "", "created_at": "2026-11-20 10:00"})


def _rec(db, item_id):
    return db._export_one("items", item_id)


def test_uzak_silme_arsive(tmp_path):
    db = Database(tmp_path)
    iid = _item(db)
    rec = _rec(db, iid)
    foto = db.photos_dir / "f1.jpg"
    foto.write_bytes(b"\xff\xd8\xff test")
    db.conn.execute("INSERT INTO item_photos(item_id, filename, sort) VALUES (?, 'f1.jpg', 0)", (iid,))
    db.conn.execute("UPDATE items SET dirty=0")
    db.conn.commit()
    remote = dict(rec, deleted=True, photos=[], mtime="2099-01-01T00:00:00.000Z")
    assert db.apply_remote("items", [remote]) == 1
    assert db.count_items() == 0                       # listeden kalktı (eşitleme durumu tutarlı)
    a = db.archive_list()
    assert len(a) == 1 and a[0]["kind"] == "silindi" and a[0]["name"] == "Matkap"
    assert foto.exists()                               # fotoğraf dosyası silinmedi
    uid = db.archive_restore(a[0]["id"])
    assert uid == rec["uid"] and db.count_items() == 1
    back = db.conn.execute("SELECT deleted, dirty FROM items WHERE uid=?", (uid,)).fetchone()
    assert back["deleted"] == 0 and back["dirty"] == 1 # geri alınan kayıt diğer cihazlara da gider
    assert db.item_photos(iid) == ["f1.jpg"]
    assert db.archive_count() == 0


def test_cakisma_yedegi(tmp_path):
    db = Database(tmp_path)
    iid = _item(db, "Eski ad")
    rec = _rec(db, iid)                                # yerelde gönderilmemiş (dirty=1) değişiklik
    remote = dict(rec, name="Uzak ad", mtime="2099-01-01T00:00:00.000Z")
    db.apply_remote("items", [remote])
    assert db.get_item(iid)["name"] == "Uzak ad"      # yeni olan kalır
    a = db.archive_list()
    assert a and a[0]["kind"] == "cakisma" and a[0]["name"] == "Eski ad"


def test_temiz_kayit_ustune_yazmada_yedek_yok(tmp_path):
    db = Database(tmp_path)
    iid = _item(db)
    rec = _rec(db, iid)
    db.conn.execute("UPDATE items SET dirty=0")
    db.conn.commit()
    db.apply_remote("items", [dict(rec, name="Yeni", mtime="2099-01-01T00:00:00.000Z")])
    assert db.archive_count() == 0


def test_eski_uzak_kayit_yok_sayilir(tmp_path):
    db = Database(tmp_path)
    iid = _item(db)
    rec = _rec(db, iid)
    assert db.apply_remote("items", [dict(rec, deleted=True, mtime="2000-01-01T00:00:00.000Z")]) == 0
    assert db.count_items() == 1 and db.archive_count() == 0


def test_cop_kutusundan_temizleme_arsivlenir(tmp_path):
    db = Database(tmp_path)
    iid = _item(db, "Vida")
    db.trash_items([iid])
    db.purge_items([iid])
    a = db.archive_list()
    assert a and a[0]["kind"] == "temizlendi" and a[0]["name"] == "Vida"


def test_yerel_ag_birlestirme_ayni_kural(tmp_path):
    from organizer import lan
    a, b = Database(tmp_path / "a"), Database(tmp_path / "b")
    iid = _item(a, "Ortak")
    lan.merge(b, a.all_records())
    assert b.count_items() == 1
    a.purge_items([iid])                               # A'da kalıcı silindi
    lan.merge(b, a.all_records())
    assert b.count_items() == 0
    kinds = [r["kind"] for r in b.archive_list()]
    assert "silindi" in kinds                          # B'de arşivde duruyor


def test_kopru_isareti_ile_eski_veri_kopyalanir(tmp_path, monkeypatch):
    """Köprü (eski taşınabilir program) eski veri klasörünü bildirir; kurulu sürüm ilk açılışta kopyalar, eskiyi silmez."""
    from organizer import paths
    eski = tmp_path / "Organizer-Tasinabilir" / "veri"
    db = Database(eski)
    _item(db, "Eski kayıt")
    db.conn.close()
    yeni = tmp_path / "AppData" / "Organizer"
    yeni.mkdir(parents=True)
    (yeni / paths.POINTER).write_text(str(eski), encoding="utf-8")
    monkeypatch.delenv("ORGANIZER_DATA", raising=False)
    assert paths.adopt_old_data(yeni) == eski
    assert Database(yeni).count_items() == 1
    assert (eski / "organizer.db").exists()
    assert paths.adopt_old_data(yeni) is None          # ikinci açılışta tekrar kopyalanmaz
