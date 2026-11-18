# Organizer (Düzenli Evim)

Ev eşyaları arşivi: Windows masaüstü programı + Android telefon uygulaması. Kayıtlar cihazlar arasında
kullanıcının Firebase hesabı üzerinden eşitlenir; **kayıtlar bu depoda bulunmaz**.

- `masaustu/` — masaüstü programın kaynağı (Python 3.12 + PySide6). Kurulu programda `_sistem\uygulama\` altındadır.
- `telefon/` — telefon uygulamasının web paketi (Android kabuğu içinde çalışır).
- `guncelleme/` — imzalı güncelleme paketleri ve bildirgeleri. Programlar yeni sürümü buradan indirir
  (`https://raw.githubusercontent.com/departures-mil/organizer/main/guncelleme/<tür>.json`).
  Her paket geliştiricinin RSA-3072 anahtarıyla imzalıdır; imzası tutmayan paket kurulmaz.
- `araclar/yayinla.py` — yeni sürüm yayınlama aracı.

## Yeni sürüm
1. Kaynakta değişikliği yap; sürümü iki tarafta aynı artır (`masaustu/organizer/__init__.py`, `telefon/app.js` 5. satır).
2. `ANAHTAR=<gizli anahtar> python3 araclar/yayinla.py masaustu masaustu "notlar"`
3. `ANAHTAR=<gizli anahtar> python3 araclar/yayinla.py telefon telefon "notlar" --kabuk 1`
4. `git add -A && git commit -m "Organizer X.Y.Z" && git push`
