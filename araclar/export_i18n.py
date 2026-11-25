"""masaustu/organizer/i18n.py → telefon/i18n.js (çeviriler tek yerden yönetilir).

Kullanım (deponun kökünden): python3 araclar/export_i18n.py
Telefonda bulunup masaüstünde olmayan eski anahtarlar korunur."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "masaustu"))
from organizer import i18n  # noqa: E402

JS = os.path.join(REPO, "telefon", "i18n.js")
src = open(JS, encoding="utf-8").read()
head = src.index("Object.assign(") + len("Object.assign(")
tail = src.index("}, {\n  lang:") + 1
data = json.loads(src[head:tail])
strings = dict(data["strings"])
for k, (en, ar) in i18n.STRINGS.items():
    strings[k] = [en, ar]
data["languages"] = [list(x) for x in i18n.LANGUAGES]
data["strings"] = strings
data["defaults"] = {k: list(v) for k, v in i18n.DEFAULT_NAMES.items()}
data["professions"] = i18n.PROFESSIONS
body = json.dumps(data, ensure_ascii=False, indent=1)
# "strings" sözlüğü satır başına bir anahtar olsun (eski biçim)
lines = ['{', ' "languages": ' + json.dumps(data["languages"], ensure_ascii=False, indent=1).replace("\n", "\n ") + ",",
         ' "strings": {']
items = list(strings.items())
for i, (k, v) in enumerate(items):
    lines.append(f' {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}' + ("," if i < len(items) - 1 else ""))
lines.append(" },")
lines.append(' "defaults": ' + json.dumps(data["defaults"], ensure_ascii=False, indent=1).replace("\n", "\n ") + ",")
lines.append(' "professions": ' + json.dumps(data["professions"], ensure_ascii=False, indent=1).replace("\n", "\n ") + "\n}")
out = src[:head] + "\n".join(lines) + src[tail:]
open(JS, "w", encoding="utf-8").write(out)
print(f"{len(strings)} çeviri yazıldı → telefon/i18n.js")

# 2.3.0: çevrim dışı çeviri sözlüğü → telefon/sozluk.js
from organizer import sozluk  # noqa: E402
SJS = os.path.join(REPO, "telefon", "sozluk.js")
with open(SJS, "w", encoding="utf-8") as f:
    f.write("/* ÜRETİLDİ — düzenlemeyin: masaustu/organizer/sozluk.py → araclar/export_i18n.py */\n"
            "const SOZLUK = " + json.dumps([list(w) for w in sozluk.WORDS], ensure_ascii=False) + ";\n")
print(f"{len(sozluk.WORDS)} sözlük kelimesi → telefon/sozluk.js")
