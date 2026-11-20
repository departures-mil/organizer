#!/bin/bash
# Organizer APK derleme: aapt2 + javac + d8 + zipalign + apksigner (Gradle gerekmez)
# assets/web = ../telefon (derlemeden önce kopyalanır) + surum.txt (telefon/app.js APP_VERSION)
set -e
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/android-sdk}
BT=$SDK/build-tools/35.0.0
PLAT=$SDK/platforms/android-34/android.jar
KEYS=${KEYS:-$HOME/w/anahtarlar}
OUT=${1:-out}
rm -rf assets/web && mkdir -p assets && cp -r ../telefon assets/web
grep -o 'APP_VERSION = "[0-9.]*"' ../telefon/app.js | grep -o '[0-9.]*[0-9]' > assets/web/surum.txt
rm -rf "$OUT" && mkdir -p "$OUT/compiled" "$OUT/classes" "$OUT/dex"
"$BT/aapt2" compile --dir res -o "$OUT/compiled/res.zip"
"$BT/aapt2" link -o "$OUT/unsigned.apk" -I "$PLAT" --manifest AndroidManifest.xml -A assets --java "$OUT/gen" "$OUT/compiled/res.zip" --auto-add-overlay
javac -source 8 -target 8 -bootclasspath "$PLAT" -classpath "$PLAT" -d "$OUT/classes" -encoding UTF-8 -Xlint:-options $(find src "$OUT/gen" -name "*.java")
"$BT/d8" --release --min-api 23 --lib "$PLAT" --output "$OUT/dex" $(find "$OUT/classes" -name "*.class")
(cd "$OUT/dex" && zip -q -u ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$KEYS/android-imza.p12" --ks-pass "pass:$(cat "$KEYS/android-sifre.txt")" --ks-key-alias duzenlievim \
  --min-sdk-version 23 --out "$OUT/Organizer.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify --print-certs "$OUT/Organizer.apk" | head -3
ls -la "$OUT/Organizer.apk"
