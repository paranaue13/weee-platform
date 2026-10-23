"""Δοκιμή Windows › Παραγωγή › Δελτίο Παραγωγής (κάρτες σε μία σειρά, βελάκι/πάνελ, διακόπτης, λίστα συσκευών).
Χρήση: python backend/scripts/test_windows_deltio.py http://127.0.0.1:PORT [screenshot.png]   (server σε ΑΝΤΙΓΡΑΦΟ βάσης: γράφει τμήματα!)"""
import sys, os, re, datetime
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
B = sys.argv[1]
bad = []
def ck(name, ok, info=''):
    print(('✓ ' if ok else '✗ ') + name, info)
    if not ok: bad.append(name)
DAY = datetime.date.today().isoformat()
with sync_playwright() as p:
    b = launch(p); errs = []
    pg = b.new_page(viewport={'width': 1300, 'height': 900}); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1200)
    pg.click('.nav button[data-view="production"]'); pg.wait_for_timeout(800)
    pg.evaluate("document.querySelectorAll('.productionTab').forEach(b=>{if(/Δελτίο/.test(b.textContent))b.click()})")
    pg.wait_for_selector('.dcard', timeout=15000); pg.wait_for_timeout(800)
    units = pg.evaluate("prodState.units.filter(u=>u.active!==false)")
    nprod = len([u for u in units if u['profile'] not in ('SUPPORT', 'MANAGEMENT')]); nsup = len([u for u in units if u['profile'] == 'SUPPORT'])
    cards = pg.locator('.dcard')
    ck('μία κάρτα ανά τμήμα παραγωγής + ΜΙΑ ενιαία «Θέσεις υποστήριξης» (τελευταία)', cards.count() == nprod + (1 if nsup else 0) and (not nsup or 'Θέσεις υποστήριξης' in cards.last.inner_text()), f'{cards.count()} κάρτες, {nprod} παραγωγής')
    ck('οι κάρτες είναι σε ΜΙΑ σειρά (ίδιο top)', pg.evaluate("new Set([...document.querySelectorAll('.dcard')].map(c=>Math.round(c.getBoundingClientRect().top))).size") == 1)
    ck('σταθερό πλάτος 360px', all(abs(w - 360) < 1 for w in pg.evaluate("[...document.querySelectorAll('.dcard')].map(c=>c.getBoundingClientRect().width)")))
    ck('οριζόντιο scroll στη σειρά', pg.evaluate("(e=>e.scrollWidth>e.clientWidth)(document.getElementById('deltioDepts'))") and pg.evaluate("getComputedStyle(document.getElementById('deltioDepts')).overflowX") == 'auto')
    ck('η κάρτα υποστήριξης ΔΕΝ έχει λίστα συσκευών', not nsup or 'ΣΥΣΚΕΥΕΣ' not in cards.last.inner_text())
    ck('οι κάρτες παραγωγής έχουν λίστα συσκευών με «Σύνολο»', 'ΣΥΣΚΕΥΕΣ ΠΟΥ ΜΠΗΚΑΝ ΣΤΟ ΤΜΗΜΑ' in cards.first.inner_text() and 'Σύνολο' in cards.first.inner_text())
    ck('ΔΕΝ υπάρχει κουμπί ρολόι', pg.query_selector('.deltioIntervalBtn') is None)
    ck('ώρες σε μορφή «8ω 00λ»', all(re.search(r'\d+ω \d\dλ|—', t) for t in pg.locator('.dcT tbody tr:not(.dcPanel) td.r').all_inner_texts()))
    ck('τμήματα Διοίκησης χωρίς κάρτα', not any(pg.query_selector(f'.dcard[data-unit="{u["id"]}"]') for u in units if u['profile'] == 'MANAGEMENT'))
    # διακόπτης
    ck('διακόπτης «Μόνο τμήματα με καταχώρηση» κλειστός αρχικά', not pg.is_checked('#deltioOnly'))
    n_all = cards.count()
    # μεταφορά δοκιμή
    emps = pg.evaluate("prodState.employees.filter(e=>e.active!==false&&(e.org_unit_ids||[]).length===1).map(e=>[e.id,e.org_unit_ids[0]])")
    prodids = [u['id'] for u in units if u['profile'] not in ('SUPPORT', 'MANAGEMENT')]
    e = next(x for x in emps if x[1] in prodids)
    key = e[1]
    pg.locator(f'.dcard[data-unit="{key}"] .dcArrow[data-emp="{e[0]}"]').click(); pg.wait_for_timeout(300)
    ck('βελάκι → γίνεται ▾ και η γραμμή παίρνει φόντο', pg.locator('.dcT tr.sel').count() == 1 and pg.locator('.dcT tr.sel .dcArrow').inner_text() == '▾')
    ck('πάνελ «<όνομα> · διάλεξε τμήμα»', 'διάλεξε τμήμα' in pg.locator('.dcPanel .dpT').inner_text())
    ck('κάθε γραμμή έχει «Μεταφορά» και «Εργασία»', pg.locator('.dcPanel .dpR').count() > 0 and pg.locator('.dcPanel .dpR button').count() == 2 * pg.locator('.dcPanel .dpR').count())
    ck('ΧΩΡΙΣ «Αφαίρεση» με 1 τμήμα', pg.locator('.dcPanel .rm').count() == 0)
    if len(sys.argv) > 2: pg.screenshot(path=sys.argv[2])
    to = pg.locator('.dcPanel button[data-k="add"]').first.get_attribute('data-to')
    pg.locator('.dcPanel button[data-k="add"]').first.click(); pg.wait_for_timeout(1800)
    ck('«Εργασία»: εμφανίζεται και στα 2 τμήματα, με «και <άλλο τμήμα>»', pg.locator(f'.dcArrow[data-emp="{e[0]}"]').count() == 2 and 'και ' in pg.locator(f'.dcard[data-unit="{key}"] tr:has(.dcArrow[data-emp="{e[0]}"])').inner_text())
    pg.locator(f'.dcard[data-unit="{key}"] .dcArrow[data-emp="{e[0]}"]').click(); pg.wait_for_timeout(300)
    ck('με 2 τμήματα: υπάρχει κόκκινη «Αφαίρεση από αυτό το τμήμα»', pg.locator('.dcPanel .rm').count() == 1)
    pg.locator('.dcPanel .rm').click(); pg.wait_for_timeout(1800)
    ck('«Αφαίρεση»: μένει μόνο στο άλλο τμήμα', pg.locator(f'.dcArrow[data-emp="{e[0]}"]').count() == 1 and pg.locator(f'.dcard[data-unit="{to}"] .dcArrow[data-emp="{e[0]}"]').count() == 1)
    pg.locator(f'.dcard[data-unit="{to}"] .dcArrow[data-emp="{e[0]}"]').click(); pg.wait_for_timeout(300)
    pg.locator(f'.dcPanel button[data-k="move"][data-to="{key}"]').click(); pg.wait_for_timeout(1800)
    ck('«Μεταφορά»: γυρνά πίσω και φεύγει από το άλλο', pg.locator(f'.dcArrow[data-emp="{e[0]}"]').count() == 1 and pg.locator(f'.dcard[data-unit="{key}"] .dcArrow[data-emp="{e[0]}"]').count() == 1)
    # διακόπτης ανοιχτός
    pg.evaluate("clearApiCache()")
    pg.check('#deltioOnly', force=True); pg.wait_for_timeout(500)
    devs = pg.evaluate("d=>api('/production/device-list?date='+d)", DAY); withdev = {d['org_unit_id'] for d in devs}
    shown = set(pg.evaluate("[...document.querySelectorAll('.dcard')].map(c=>c.dataset.unit)"))
    ck('διακόπτης ON: μόνο τμήματα με καταχώρηση, χωρίς «Θέσεις υποστήριξης»', shown == (withdev & set(prodids)) and 'support' not in shown, f'{len(shown)} κάρτες')
    pg.uncheck('#deltioOnly', force=True); pg.wait_for_timeout(500)
    ck('διακόπτης OFF: ξανά όλα', pg.locator('.dcard').count() == n_all)
    ck('σφάλματα σελίδας', not errs, str(errs[:2]))
    b.close()
print('ΑΠΟΤΥΧΙΕΣ:', bad)
sys.exit(1 if bad else 0)
