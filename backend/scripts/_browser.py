"""Εκκίνηση browser για δοκιμές/screenshots — ΜΟΝΟ ο δικός μας browser.

ΚΑΝΟΝΑΣ: ποτέ τερματισμός διεργασιών με όνομα εικόνας (chrome, code, electron, node, python, msedge…) ή με /T (δέντρο).
Ο προσωπικός Chrome του χρήστη δεν πρέπει να αγγίζεται ποτέ.

Το Chromium του Playwright τρέχει με δικό του προσωρινό προφίλ (όχι το προφίλ του χρήστη) και επικοινωνεί με pipe, άρα δεν
μοιράζεται τίποτα με τον Chrome του χρήστη. Εδώ φροντίζουμε να κλείνει ΜΟΝΟ αυτός ο browser, μέσω του handle του
(b.close()), ακόμα και αν το script διακοπεί (Ctrl+C / SIGTERM / τέλος διεργασίας).
"""
import atexit
import signal
import sys


def launch(p, **kw):
    b = p.chromium.launch(**kw)

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
