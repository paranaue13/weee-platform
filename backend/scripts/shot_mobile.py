r"""Στιγμιότυπα της οθόνης Android (/mobile) όπως τη δείχνει η εφαρμογή (WebView), για να τη «βλέπει» το Claude.

Χρήση (ΠΑΝΤΑ σε διακομιστή με ΑΝΤΙΓΡΑΦΟ δεδομένων, π.χ. πόρτα 8010):
  backend\.venv\Scripts\python.exe backend\scripts\shot_mobile.py http://127.0.0.1:8010 [φάκελος_εξόδου]
Βγάζει PNG: 01_login, 02_forks (Πιρούνια), 03_clamp (Πλάκες), 04_deltio (Δελτίο Ημέρας). Μέγεθος κινητού 412x915.
Δεν κλείνει κανένα άλλο Chrome· ανοίγει/κλείνει μόνο το δικό του."""
import sys, os
from playwright.sync_api import sync_playwright
from _browser import launch   # δικός μας browser, κλείνει μόνο με το handle του (ποτέ τερματισμός με όνομα εικόνας)
base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8010').rstrip('/')
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get('TEMP', '.'), 'mobile_shots')
os.makedirs(out, exist_ok=True)
with sync_playwright() as p:
    b = launch(p)
    try:
        pg = b.new_page(viewport={'width': 412, 'height': 915}, device_scale_factor=2, is_mobile=True, has_touch=True)
        pg.set_default_timeout(20000)
        pg.goto(base + '/mobile', wait_until='networkidle')
        pg.screenshot(path=os.path.join(out, '01_login.png'))
        pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(out, '02_forks.png'), full_page=True)
        pg.click('#modeClamp'); pg.wait_for_timeout(1200)
        pg.screenshot(path=os.path.join(out, '03_clamp.png'), full_page=True)
        pg.click('#topDeltioBtn'); pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(out, '04_deltio.png'), full_page=True)
        print('OK ->', out)
    finally:
        b.close()
