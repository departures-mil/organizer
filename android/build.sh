#!/bin/bash
# Organizer APK derleme (Gradle'sız): aapt2 + javac + d8 + zipalign + apksigner.
#   bash android/build.sh [çıktı klasörü]     → <çıktı>/Organizer-<sürüm>.apk
# Sürüm: masaustu/organizer/__init__.py __version__ (tek kaynak; telefon/app.js APP_VERSION testlerle denetlenir).
# versionCode = X*10000 + Y*100 + Z (2.2.0 → 20200; kurulu en eski APK 20111'den büyük olmalı).
# assets/web = ../telefon (derlemeden önce kopyalanır) + surum.txt.
# Android SDK: $ANDROID_TOOLS (bt/<sürüm>/, pf/android-NN/) ya da $ANDROID_HOME / $ANDROID_SDK_ROOT (build-tools/, platforms/).
# İmza (sırayla): ANDROID_KEYSTORE (dosya) + ANDROID_KEYSTORE_PASS (+ ANDROID_KEY_ALIAS; yoksa keystore'dan keytool ile bulunur,
#   ANDROID_KEY_PASS; yoksa = KEYSTORE_PASS) ya da eski yerel $KEYS/android-imza.p12 + android-sifre.txt (alias duzenlievim).
#   Anahtar yoksa APK_IMZASIZ=1 ile yalnız derleme denenir. Bütün sürümler AYNI anahtarla imzalanmalı.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
OUT="${1:-out}"
SURUM="$(grep -o '__version__ = "[0-9.]*"' "$ROOT/masaustu/organizer/__init__.py" | grep -o '[0-9][0-9.]*')"
IFS=. read -r MA MI PA <<< "$SURUM"
KOD=$((MA * 10000 + MI * 100 + PA))

if [ -n "${ANDROID_TOOLS:-}" ]; then
  BT="$(ls -d "$ANDROID_TOOLS"/bt/*/ | sort -V | tail -1)"; PF="$ANDROID_TOOLS/pf"
else
  SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/android-sdk}}"
  BT="$(ls -d "$SDK"/build-tools/*/ | sort -V | tail -1)"; PF="$SDK/platforms"
fi
BT="${BT%/}"
PLAT="$(ls "$PF"/android-*/android.jar | sort -V | tail -1)"
echo "build-tools: $BT  platform: $PLAT  sürüm: $SURUM ($KOD)"

rm -rf assets/web && mkdir -p assets && cp -r ../telefon assets/web
rm -rf assets/web/test
echo "$SURUM" > assets/web/surum.txt
rm -rf "$OUT" && mkdir -p "$OUT/compiled" "$OUT/classes" "$OUT/dex" "$OUT/gen"
sed -e "s/@VERSION_CODE@/$KOD/" -e "s/@VERSION_NAME@/$SURUM/" AndroidManifest.xml > "$OUT/AndroidManifest.xml"
"$BT/aapt2" compile --dir res -o "$OUT/compiled/res.zip"
"$BT/aapt2" link -o "$OUT/unsigned.apk" -I "$PLAT" --manifest "$OUT/AndroidManifest.xml" -A assets --java "$OUT/gen" \
  --min-sdk-version 23 --target-sdk-version 34 "$OUT/compiled/res.zip" --auto-add-overlay
javac -nowarn -source 8 -target 8 -bootclasspath "$PLAT" -classpath "$PLAT" -d "$OUT/classes" -encoding UTF-8 -Xlint:-options \
  $(find src "$OUT/gen" -name "*.java") 2>&1 | grep -v '^Note:\|^warning' || true
ls "$OUT/classes/com/organizer/app/MainActivity.class" "$OUT/classes/com/organizer/app/FcBridge.class" \
   "$OUT/classes/com/departuresmil/ortak/ApkPatchInstaller.class" >/dev/null
"$BT/d8" --release --min-api 23 --lib "$PLAT" --output "$OUT/dex" $(find "$OUT/classes" -name "*.class")
(cd "$OUT/dex" && zip -q -u ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

KS="${ANDROID_KEYSTORE:-}"; PW="${ANDROID_KEYSTORE_PASS:-}"; AL="${ANDROID_KEY_ALIAS:-}"
KEYS="${KEYS:-$HOME/w/anahtarlar}"
if [ -z "$KS" ] && [ -f "$KEYS/android-imza.p12" ]; then
  KS="$KEYS/android-imza.p12"; PW="$(cat "$KEYS/android-sifre.txt")"; AL="${AL:-duzenlievim}"
fi
if [ -z "$KS" ]; then
  [ -n "${APK_IMZASIZ:-}" ] || { echo "İmza anahtarı yok (ANDROID_KEYSTORE)"; exit 3; }
  cp "$OUT/aligned.apk" "$OUT/Organizer-$SURUM-imzasiz.apk"; echo "İMZASIZ: $OUT/Organizer-$SURUM-imzasiz.apk"; exit 0
fi
if [ -z "$AL" ]; then
  # alias verilmediyse keystore'daki ilk anahtar girdisi (PKCS12 / JKS)
  AL="$(keytool -list -v -keystore "$KS" -storepass "$PW" 2>/dev/null | sed -n 's/^Alias name: //p; s/^Takma ad: //p' | head -1)"
  [ -n "$AL" ] || { echo "Keystore'da anahtar adı (alias) bulunamadı"; exit 4; }
  echo "alias: $AL"
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$PW" --key-pass "pass:${ANDROID_KEY_PASS:-$PW}" --ks-key-alias "$AL" \
  --min-sdk-version 23 --out "$OUT/Organizer-$SURUM.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify --print-certs "$OUT/Organizer-$SURUM.apk" | head -3
ls -la "$OUT/Organizer-$SURUM.apk"
