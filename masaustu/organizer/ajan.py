"""Asistan Agent bağlantısı (organizer/fc_agent.py = ortak-cekirdek/python/fc_agent.py)."""
AJAN = None


def kur(app):
    global AJAN
    try:
        from . import fc_agent, i18n, __version__
        AJAN = fc_agent.Agent("organizer", __version__, lang=lambda: i18n.LANG, sync=True)
    except Exception:
        AJAN = None
    return AJAN


def pencere(app, win, ilk):
    if AJAN is None:
        return
    try:
        AJAN.start(app, win) if ilk else AJAN.attach_button(win)
    except Exception:
        pass
