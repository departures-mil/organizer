"""Organizer: ev eşyaları arşivi."""

# İç sürüm numarası. Baştaki "2." sürüm dizisidir (1.x dizisi 1.4.0'da bitti); kullanıcıya gösterilmez.
# Ekranda "v.1.0.3" olarak görünür. Bir sonraki sürüm 2.1.0.4 → "v.1.0.4" olur.
__version__ = "2.1.0.4"


def goster(v=None):
    """İç sürüm numarasını ekranda gösterilecek biçime çevirir: "2.1.0.1" → "v.1.0.1"."""
    v = str(__version__ if v is None else v or "").strip()
    if not v:
        return ""
    parts = v.split(".")
    if len(parts) == 4 and parts[0] == "2":
        parts = parts[1:]
    return "v." + ".".join(parts)
