import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Program dosyalarının (assets) bulunduğu klasör."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def asset(name: str) -> str:
    p = resource_dir() / "assets" / name
    if not p.exists():
        # güncelleme paketinde yoksa programın kendi klasöründeki kopyayı kullan
        try:
            alt = Path(sys.argv[0]).resolve().parent / "assets" / name
            if alt.exists():
                return str(alt)
        except Exception:
            pass
    return str(p)


def data_dir() -> Path:
    """Veritabanı ve fotoğrafların tutulduğu klasör.

    Programın yanında "veri" adlı bir klasör varsa taşınabilir modda oraya yazılır,
    yoksa Windows'ta %APPDATA%\\Organizer kullanılır.
    """
    env = os.environ.get("ORGANIZER_DATA")
    if env:
        d = Path(env)
    else:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else resource_dir()
        if (base / "veri").is_dir():
            d = base / "veri"
        elif sys.platform == "win32":
            d = Path(os.environ.get("APPDATA", Path.home())) / "Organizer"
        else:
            d = Path.home() / ".local" / "share" / "Organizer"
    (d / "fotograflar" / "kucuk").mkdir(parents=True, exist_ok=True)
    return d


OLD_DB_NAMES = ("organizer.db", "duzenli_evim.db")   # Organizer ve ondan önceki Düzenli Evim sürümleri
OLD_FOLDER_PREFIXES = ("organizer", "duzenlievim")


def _old_db(folder: Path):
    """Klasördeki (varsa) veritabanı dosyası: önce Organizer'ınki, yoksa Düzenli Evim'inki."""
    for name in OLD_DB_NAMES:
        if (folder / name).exists():
            return folder / name
    return None


def _old_data_folders(target: Path):
    """Eski verilerin bulunabileceği yerler: aynı klasördeki eski taşınabilir sürümler
    (ör. Organizer-v1.0.0-Tasinabilir\\veri ya da DuzenliEvim-v4.2-Tasinabilir\\veri) ve
    bilgisayarda kurulu sürümün klasörü."""
    found = []
    here = target.parent          # ...\Organizer-v1.0.1-Tasinabilir
    try:
        for sib in here.parent.iterdir():
            if sib != here and sib.is_dir() and sib.name.lower().startswith(OLD_FOLDER_PREFIXES):
                found.append(sib / "veri")
        # RAR'lar yan yana açıldıysa: ...\DuzenliEvim-v4.1\Bilgisayar\DuzenliEvim-v4.2-Tasinabilir
        if here.parent.name.lower() == "bilgisayar":
            for base in (here.parent.parent, here.parent.parent.parent):
                for pat in ("Bilgisayar/[Oo]rganizer*/veri", "*/Bilgisayar/[Oo]rganizer*/veri",
                            "Bilgisayar/[Dd]uzenli[Ee]vim*/veri", "*/Bilgisayar/[Dd]uzenli[Ee]vim*/veri"):
                    found += base.glob(pat)
    except OSError:
        pass
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        found += [appdata / "Organizer", appdata / "DuzenliEvim"]
    out = []
    for f in found:
        db = _old_db(f)
        try:
            if db and f.resolve() != target.resolve():
                out.append((db.stat().st_mtime, f))
        except OSError:
            pass
    return [f for _, f in sorted(out, key=lambda x: x[0], reverse=True)]


POINTER = "eski-veri-konumu.txt"   # 2.2.0 köprüsü: eski taşınabilir sürümün veri klasörü (kurulu sürüm oradan kopyalar)


def _pointer_folder(target: Path):
    """Köprü sürümünün (eski taşınabilir program) bıraktığı işaret: eski veri klasörü."""
    try:
        p = Path((target / POINTER).read_text(encoding="utf-8").strip())
    except OSError:
        return None
    try:
        if _old_db(p) and p.resolve() != target.resolve():
            return p
    except OSError:
        pass
    return None


def adopt_old_data(target: Path):
    """Yeni sürüm ilk kez açıldığında eski verileri (Firebase ayarları dahil bütün ayarlar, kayıtlar, fotoğraflar)
    kopyalar: köprünün bildirdiği eski taşınabilir klasör (2.2.0 kurulumu), en son kullanılan eski taşınabilir klasör
    ya da bilgisayarda kurulu sürüm. Eski veriler silinmez. Kopyalanan yeri döndürür."""
    import shutil
    import sqlite3
    if (target / "organizer.db").exists():
        return None
    old = _pointer_folder(target)
    if old is None:
        if not os.environ.get("ORGANIZER_DATA"):
            return None
        olds = _old_data_folders(target)
        if not olds:
            return None
        old = olds[0]
    target.mkdir(parents=True, exist_ok=True)
    for f in old.iterdir():
        dest = target / f.name
        if f.name in ("guncelleme", "fccore", POINTER):   # eski sürümün kendi güncellemeleri taşınmaz
            continue
        if f.is_dir():
            shutil.copytree(f, dest, dirs_exist_ok=True)
        elif f.name in OLD_DB_NAMES:
            # SQLite yedekleme: henüz ana dosyaya yazılmamış (-wal) değişiklikler de gelir.
            # Düzenli Evim'in duzenli_evim.db dosyası organizer.db adıyla kopyalanır.
            if f != _old_db(old):
                continue
            src = sqlite3.connect(str(f))
            dst = sqlite3.connect(str(target / "organizer.db"))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        elif not f.name.endswith(("-wal", "-shm", "hata-kaydi.txt")):
            shutil.copy2(f, dest)
    return old
