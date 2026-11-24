"""Organizer: ev eşyaları arşivi."""

# Sürüm: semver X.Y.Z (2.2.0'dan beri; ekranda ve içeride aynı). 2.1.0.x dizisinin (ekranda v.1.0.x) devamıdır:
# eski güncelleyiciler sayıları sırayla karşılaştırır, 2.2.0 > 2.1.0.13 olduğu için eski kurulumlar bunu "yeni" görür.
__version__ = "2.2.3"


def goster(v=None):
    """Ekranda gösterilecek sürüm: "2.2.0" → "v2.2.0" (eski 4 parçalı iç numara "2.1.0.12" → "v.1.0.12")."""
    v = str(__version__ if v is None else v or "").strip()
    if not v:
        return ""
    parts = v.split(".")
    if len(parts) == 4 and parts[0] == "2":
        return "v." + ".".join(parts[1:])
    return "v" + v
