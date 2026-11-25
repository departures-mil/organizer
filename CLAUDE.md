# Organizer — çalışma kuralları

- Kullanıcı "BAŞLA" demeden yeni iş başlatma. Yazışma dili Türkçe. Arayüz tr/en/ar (Arapça RTL).
- Ortak çekirdek gömülüdür (`cekirdek/VERSION`): masaüstü `masaustu/fccore` (Python/PySide6), telefon `telefon/cekirdek`
  (web, yerel ek: `FC.host.update.run` → Android Java tarafı indirme), Java `android/src/com/departuresmil/ortak`.
  ortak-cekirdek deposunu buradan değiştirme; yerel düzeltmeyi `cekirdek/VERSION`'a yaz.
- Sürüm semver X.Y.Z, etiket tam `vX.Y.Z`. Her güncellemede: `masaustu/organizer/__init__.py`, `telefon/app.js` APP_VERSION,
  `release-notes.json`, `masaustu/organizer/app.py` NEWS. Testler tutarlılığı denetler.
- Yayın yalnız GitHub Releases (CI, bkz. README). Eski `guncelleme/` kanalı yalnız 2.1.0.x köprüsü içindir (RSA anahtarı
  CI'da YOK: `python araclar/kopru.py --gonder` kullanıcının bilgisayarında).
- Görünüm: varsayılan Falcon şeması + şema seçici; eski renkler `klasik` (masaüstü `theme.py`, telefon `kabuk.js`).
  Sağ üst: [Fiyatları gizle · Hızlı ara · Duyurular] · Eşitle · Wi‑Fi · Güncelle · Tema · Dil | Küçült · Orta · Tam ekran · Kapat.
  Ayarlar'da "Admin ile iletişim" EN SONDA. Masaüstü her açılışta tam ekran.
- Eşitleme kuralı: hiçbir kayıt kalıcı silinmez — uzak silme → Arşiv, gönderilmemiş yerel değişikliğin üstüne yazma →
  çakışma yedeği (masaüstü `db.apply_remote` + `arsiv` tablosu; telefon `Store.applyRemote` + `arsiv_v1`). Bulut ve yerel ağ aynı yoldan geçer.
- Veri yerleri ve paket adı değişmez: `%APPDATA%\Organizer`, `com.organizer.app`. APK'lar hep aynı anahtarla imzalanır.
- APK/exe kullanıcıya dosya olarak gönderilmez.
