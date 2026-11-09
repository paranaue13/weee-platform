"""Χειροκίνητη σύνδεση στο portal «Ανακύκλωση Συσκευών Α.Ε.» (https://eweee.electrocycle.gr) με το προφίλ browser του συγχρονισμού.
Ανοίγει ορατό παράθυρο στη σελίδα της Ζωντανής ροής· συνδέεσαι ΕΣΥ (email/κωδικός/OTP) και κλείνεις το παράθυρο. Το προφίλ
(electrocycle_profile) κρατά την εμπιστοσύνη της συσκευής, ώστε ο συγχρονισμός να συνεχίσει μόνος του. ΔΕΝ αποθηκεύονται κωδικοί
πουθενά στον κώδικα. Χρήση (με ΚΛΕΙΣΤΟ τον server ή αφού περάσει ο συγχρονισμός): python scripts/electrocycle_login.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from playwright.sync_api import sync_playwright
from app.config import settings
from app.electrocycle_sync import FLOW_URL

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(settings.electrocycle_profile_dir, headless=False, viewport={"width": 1300, "height": 900})
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto(FLOW_URL)
    print("Συνδέσου στο παράθυρο που άνοιξε και μετά κλείσε το παράθυρο.")
    try: pg.wait_for_event("close", timeout=0)
    except Exception: pass
    ctx.close()
