# Organizer

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
   Sürüm numarası: ekranda **v.1.0.1, v.1.0.2 …** görünür. İç numara başına sürüm dizisi `2.` eklenmiş halidir
   (`2.1.0.1` → v.1.0.1, `2.1.0.2` → v.1.0.2). Eski 1.x dizisi 1.4.0'da bitti; dizi öneki eski kurulumların
   yeni sürümü "daha yeni" olarak görmesini sağlar. Ekrana çeviri `goster()` ile yapılır.
2. `ANAHTAR=<gizli anahtar> python3 araclar/yayinla.py masaustu masaustu "notlar"`
3. `ANAHTAR=<gizli anahtar> python3 araclar/yayinla.py telefon telefon "notlar" --kabuk 1`
4. `git add -A && git commit -m "Organizer X.Y.Z" && git push`

## v.1.0.10 (2026-11-22 yayınlandı; commit 31c7688)
- Ayarlar > Kullanım Limitleri (masaüstü `organizer/kullanim_sayac.py`, telefon `telefon/kullanim.js`; ortak kaynak
  `departures-mil/duyurular/istemci`). Firestore istekleri `_request` içinde sayılır.
- Programla gelen ortak Firebase projesi (duzenli-evim) kaldırıldı: herkes kendi ücretsiz Firebase hesabını kullanır
  (rehber: duyurular/firebase-kurulum.md). Eski ortak projeye bağlı kurulumlardan yalnız yönetici hesabı (yonetici@example.invalid)
  ayarı kendine kaydedilip devam eder; diğerlerinin bağlantısı kesilir ve kendi hesabını bağlaması istenir.
- Yayınlamak için: `ANAHTAR=... python3 araclar/yayinla.py masaustu masaustu "notlar"` + `... telefon telefon "notlar" --kabuk 1`.

## Asistan Agent (telefon + masaüstü 2.1.0.13; masaüstü `organizer/fc_agent.py` = ortak-cekirdek/python/fc_agent.py, bağlantı `organizer/ajan.py`)
✦ Asistan Agent eklendi: `fc-agent.js` (= ortak-cekirdek/web/dist/fc-agent.js) + `agent-baslat.js` arayüz klasöründe. Bütün programlardaki
çalışmayı sayılarla izler, öneri verir (bildirim + ✦ panel), Ayarlar'da admin iletişim kartının önünde. Sonraki sürüm yayınlanınca kullanıcılara gider.
