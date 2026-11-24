import os
import re
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    """organizer/paths.py data_dir() ile aynı kural (paketi yüklemeden önce gerekiyor)."""
    env = os.environ.get("ORGANIZER_DATA")
    if env:
        return env
    if os.path.isdir(os.path.join(HERE, "veri")):
        return os.path.join(HERE, "veri")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Organizer")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "Organizer")


def _log_file():
    folder = os.environ.get("ORGANIZER_DATA") or HERE
    return os.path.join(folder, "hata-kaydi.txt")


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def _version_in(folder):
    try:
        with open(os.path.join(folder, "organizer", "__init__.py"), encoding="utf-8") as f:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def _updated_folder():
    """Uygulama içinden kurulmuş güncelleme varsa ve programla gelenden yeniyse onun klasörü."""
    root = os.path.join(_data_dir(), "guncelleme")
    try:
        with open(os.path.join(root, "etkin.txt"), encoding="utf-8") as f:
            ver = f.read().strip()
    except OSError:
        return None, ""
    folder = os.path.join(root, "organizer-masaustu-" + ver)
    if not ver or _version_in(folder) != ver or _vkey(ver) <= _vkey(_version_in(HERE)):
        return None, ""
    return folder, ver


def _give_up_update(ver):
    """Güncellenmiş sürüm açılamadı: bir önceki sürüme (yoksa programla gelene) dön, bu sürümü bir daha önerme."""
    root = os.path.join(_data_dir(), "guncelleme")
    try:
        with open(os.path.join(root, "onceki.txt"), encoding="utf-8") as f:
            prev = f.read().strip()
    except OSError:
        prev = ""
    if prev and _version_in(os.path.join(root, "organizer-masaustu-" + prev)) != prev:
        prev = ""
    try:
        with open(os.path.join(root, "etkin.txt"), "w", encoding="utf-8") as f:
            f.write(prev)
        with open(os.path.join(root, "onceki.txt"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(root, "bozuk.txt"), "a", encoding="utf-8") as f:
            f.write(ver + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    if sys.stderr is None:  # pythonw ile (konsolsuz) açıldığında hatalar bir dosyaya yazılsın
        try:
            sys.stderr = sys.stdout = open(_log_file(), "a", encoding="utf-8")
        except OSError:
            pass
    # 2.1'in uygulama içi paket güncellemesi (veri/guncelleme/etkin.txt) yalnız eski taşınabilir kurulumda geçerliydi;
    # 2.2.0'dan beri program kurulumla gelir ve fccore ile güncellenir (PyInstaller: sys.frozen) → eski paketler yüklenmez.
    folder, ver = (None, "") if getattr(sys, "frozen", False) else _updated_folder()
    if folder:
        sys.path.insert(0, folder)
        os.environ["ORGANIZER_OTA"] = ver
        os.environ["ORGANIZER_DATA"] = _data_dir()   # güncellenen paket de aynı veri klasörünü kullansın
    try:
        from organizer.app import run
        sys.exit(run())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        if folder and not os.environ.get("ORGANIZER_BASLADI"):
            _give_up_update(ver)
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, f"Güncellenen sürüm ({ver}) açılamadı.\n\nÖnceki sürüme dönüldü; kayıtlarınız yerinde.\n"
                          f"Ayrıntılar: {_log_file()}", "Organizer", 0x30)
            subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=HERE)
            sys.exit(1)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, "Organizer açılırken bir hata oluştu.\n\nAyrıntılar: " + _log_file(), "Organizer", 0x10)
        raise
