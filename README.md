# Organizer (Düzenli Evim)

Ev eşyaları arşivi: Windows masaüstü programı + Android telefon uygulaması. Kayıtlar cihazlar arasında
kullanıcının kendi Firebase hesabı üzerinden (ve aynı Wi‑Fi'de yerel ağ eşitlemesiyle) eşitlenir; **kayıtlar bu depoda bulunmaz**.

- `masaustu/` — masaüstü (Python 3.12 + PySide6) + `masaustu/fccore/` ortak çekirdeğin Python sürümü (gömülü kopya).
  Kurulu program: `%LOCALAPPDATA%\Programs\Organizer` (NSIS, kullanıcı başına). Kayıtlar: `%APPDATA%\Organizer` (değişmez).
- `telefon/` — telefon arayüzü (web) + `telefon/cekirdek/` ortak web çekirdeği. `android/` — Java WebView kabuğu (paket `com.organizer.app`).
- `cekirdek/VERSION` — gömülü ortak çekirdeğin commit'i ve yerel düzeltmeler.
- `kurulum/organizer.nsi` — Windows kurulumu. `masaustu/organizer.spec` — PyInstaller (one-dir).
- `guncelleme/` — YALNIZ eski (2.1.0.x) kurulumlar için RSA imzalı köprü bildirgeleri (`araclar/kopru.py`).

## Sürüm ve yayın (2.2.0'dan beri)
- Sürüm semver `X.Y.Z`, etiket `vX.Y.Z`; ekranda da aynı. Tek kaynak `masaustu/organizer/__init__.py`;
  `telefon/app.js` `APP_VERSION` aynı olmalı (test denetler). `release-notes.json` (tr/en/ar) + `masaustu/organizer/app.py` NEWS.
  APK versionCode = X·10000 + Y·100 + Z.
- Güncelleme yalnız GitHub Releases + `latest.json` + FCD1 yama (ortak `reusable-release.yml`): kanallar
  `win-app` (PyInstaller klasörünün fcpack zip'i), `win-setup` (NSIS), `android` (APK; yama = kurulu APK + yama → yeni APK).
- CI `.github/workflows/release.yml`: test (pytest offscreen + Playwright telefon testi + köprü kuru) → Windows derleme → APK
  (secret'lar: ANDROID_KEYSTORE_B64, ANDROID_KEYSTORE_PASS, [ANDROID_KEY_PASS], [ANDROID_KEY_ALIAS]) → release.
  Yayın: main'de `gh api -X POST repos/departures-mil/organizer/actions/workflows/release.yml/dispatches -f ref=main`.
- Eski kurulumlar (2.1.0.x) için köprü — release'ten SONRA, RSA anahtarının olduğu bilgisayarda: `python araclar/kopru.py --gonder`.

## Test
- `cd masaustu && QT_QPA_PLATFORM=offscreen python -m pytest -q tests`
- `node araclar/test-telefon.js` (PLAYWRIGHT_CORE / PLAYWRIGHT_BROWSERS_PATH)
- Ekran görüntüleri: `QT_QPA_PLATFORM=offscreen python3 araclar/ekran.py <klasör>` ve `node araclar/ekran-telefon.js <klasör>`
- APK (imzasız deneme): `ANDROID_TOOLS=<sdk> APK_IMZASIZ=1 bash android/build.sh /tmp/apk`
