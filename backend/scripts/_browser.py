"""Εκκίνηση browser για δοκιμές/screenshots — ΜΟΝΟ ο δικός μας browser.

ΚΑΝΟΝΑΣ: ποτέ τερματισμός διεργασιών με όνομα εικόνας (chrome, code, electron, node, python, msedge…) ή με /T (δέντρο).
Ο προσωπικός Chrome του χρήστη δεν πρέπει να αγγίζεται ποτέ.

Το Chromium του Playwright τρέχει με δικό του προσωρινό προφίλ (όχι το προφίλ του χρήστη) και επικοινωνεί με pipe, άρα δεν
μοιράζεται τίποτα με τον Chrome του χρήστη. Εδώ φροντίζουμε να κλείνει ΜΟΝΟ αυτός ο browser, μέσω του handle του
(b.close()), ακόμα και αν το script διακοπεί (Ctrl+C / SIGTERM / τέλος διεργασίας).
"""
import atexit
import os
import signal
import sys


def launch(p, **kw):
    # WEEE_SCROLLBARS=1: ΟΡΑΤΕΣ μπάρες scroll όπως στον πραγματικό Chrome (το headless τις κρύβει και οι μπάρες δεν παίρνουν πλάτος· έτσι δεν φαίνονται λάθη πλάτους)
    import os
    if os.environ.get("WEEE_SCROLLBARS") == "1" and "ignore_default_args" not in kw:
        kw["ignore_default_args"] = ["--hide-scrollbars"]
    b = p.chromium.launch(**kw)

    # WEEE_MENUPOS=top|bottom|left: δοκιμές με συγκεκριμένη «Θέση μενού» (ρύθμιση στο localStorage της δοκιμής)
    _mp = os.environ.get("WEEE_MENUPOS")
    if _mp in ("top", "bottom", "left"):
        _nc = b.new_context
        _js = "try{localStorage.setItem('weee.menupos.last','%s')}catch(e){}" % _mp

        def _new_context(*a, **k):
            c = _nc(*a, **k)
            c.add_init_script(_js)
            return c
        b.new_context = _new_context

        def _new_page(*a, **k):  # τα ορίσματα (viewport κ.λπ.) πάνε στο context
            return _new_context(**k).new_page()
        b.new_page = _new_page

    def _close(*_):
        try:
            b.close()
        except Exception:
            pass

    atexit.register(_close)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *a: (_close(), sys.exit(1)))
        except Exception:
            pass
    return b
