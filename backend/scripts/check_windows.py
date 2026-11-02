"""Έλεγχος παραθύρων (μέρος του check_tables.py): για τα τρία είδη παραθύρων (Προφίλ/φόρμες #floatingEditor, Νέα Παραλαβή #receiptForm,
Ταξινόμηση #sortingDetail) ελέγχει (1) επικεφαλίδα ~48px, (2) τίτλος και κουμπιά —▢✕ κεντραρισμένα στο ύψος της επικεφαλίδας,
(3) ελαχιστοποιημένα παράθυρα = κουτάκια μέσα στη μπάρα κάτω αριστερά, χωρίς επικάλυψη μεταξύ τους, με τα τρία κουμπιά μέσα στο κουτάκι,
(4) η μπάρα «Μέγεθος» έχει ύψος 42px και γραμματοσειρά ίδια με του αριστερού πάνελ.
Τυπώνει μόνο προβλήματα. Μόνο ανάγνωση (πλοήγηση, χωρίς αποθήκευση)."""
import sys
from playwright.sync_api import sync_playwright
from _browser import launch

GEOM = """(sel)=>{const w=document.querySelector(sel);if(!w||w.classList.contains('hidden'))return null;const r=w.getBoundingClientRect();
 const hdr=w.querySelector('.floatPanelHeader,.uHdrWrap>.uHdr,.sortingPopupTopRow');const hr0=hdr.getBoundingClientRect();const isS=hdr.classList.contains('sortingPopupTopRow');const hr={top:hr0.top,height:isS?(w.classList.contains('popupMin')?hr0.height:48):hr0.height};
 const t=w.querySelector('h3,h2').getBoundingClientRect();
 const ctls=[...w.querySelectorAll('.winCtl')].map(c=>c.getBoundingClientRect());
 return {win:[r.left,r.top,r.width,r.height],hdr:[hr.top,hr.height],title:t.top+t.height/2,ctls:ctls.map(q=>[q.left,q.top,q.width,q.height]),min:w.classList.contains('popupMin')}}"""


def run(B='http://127.0.0.1:8000'):
    problems = []
    with sync_playwright() as p:
        b = launch(p)
        try:
            pg = b.new_page(viewport={'width': 1366, 'height': 800})
            pg.goto(B + '/', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
            wins = [
                ('Παράθυρο φόρμας (#floatingEditor)', "show('master');document.querySelector('.mtab[data-mtab=materialsM]').click();setTimeout(()=>document.getElementById('materialCreate').click(),300)", '#floatingEditor', '#floatingEditorMin'),
                ('Νέα Παραλαβή (#receiptForm)', "show('receipts');prepareNewReceiptPopup()", '#receiptForm', '#receiptMin'),
            ]
            sd = pg.evaluate("(async()=>{try{show('receipts');let r=await api('/receipts');let l=(r.find(x=>x.loads&&x.loads.length)||{loads:[]}).loads[0];return l?l.id:null}catch(e){return null}})()")
            if sd: wins.append(('Ταξινόμηση (#sortingDetail)', f"show('receipts');openSortingDetail('{sd}')", '#sortingDetail', '#sortingDetail [data-win=min]'))
            for name, js, sel, minId in wins:
                pg.evaluate(js); pg.wait_for_timeout(1500)
                g = pg.evaluate(GEOM, sel)
                if not g: problems.append(f'[{name}] δεν άνοιξε'); continue
                if abs(g['hdr'][1] - 48) > 1.5: problems.append(f"[{name}] ύψος επικεφαλίδας {g['hdr'][1]:.0f}px (πρέπει 48)")
                hc = g['hdr'][0] + g['hdr'][1] / 2
                for q in g['ctls']:
                    if abs(q[1] + q[3] / 2 - hc) > 1.5: problems.append(f"[{name}] κουμπί παραθύρου όχι κεντραρισμένο ({q[1] + q[3] / 2:.0f} αντί {hc:.0f})")
                if abs(g['title'] - hc) > 2.5: problems.append(f"[{name}] ο τίτλος δεν είναι κεντραρισμένος ({g['title']:.0f} αντί {hc:.0f})")
            # ελαχιστοποίηση πολλών μαζί
            pg.evaluate("document.querySelectorAll('#floatingEditor,#receiptForm,#sortingDetail').forEach(e=>e.classList.add('hidden'))")
            for name, js, sel, minId in wins:
                pg.evaluate(js); pg.wait_for_timeout(1200)
                if minId: pg.evaluate(f"document.querySelector('{minId}').click()"); pg.wait_for_timeout(300)
            pg.wait_for_timeout(500)
            bar = pg.evaluate("(()=>{const z=document.getElementById('zoomBar'),r=z.getBoundingClientRect();return [r.left,r.top,r.width,r.height,parseFloat(getComputedStyle(z).fontSize),parseFloat(getComputedStyle(document.querySelector('.nav button')).fontSize)]})()")
            if abs(bar[3] - 42) > 1.5: problems.append(f'[μπάρα Μέγεθος] ύψος {bar[3]:.0f}px (πρέπει 42)')
            if abs(bar[4] - bar[5]) > 0.5: problems.append(f'[μπάρα Μέγεθος] γραμματοσειρά {bar[4]}px ≠ αριστερό πάνελ {bar[5]}px')
            # νέο μοντέλο: το ελαχιστοποιημένο παράθυρο κρύβεται και μπαίνει κουμπί (δύο γραμμές) στη μπάρα κάτω αριστερά, με τη σειρά που ανοίχτηκαν
            for name, js, sel, minId in wins:
                if not minId: continue
                if pg.evaluate("(s)=>{let e=document.querySelector(s);return !!e&&getComputedStyle(e).display!=='none'}", sel) and pg.evaluate("(s)=>document.querySelector(s).classList.contains('popupMin')", sel):
                    problems.append(f'[{name}] το ελαχιστοποιημένο παράθυρο φαίνεται ακόμα στην οθόνη')
            chips = pg.evaluate("[...document.querySelectorAll('#winDock .wChip')].map(c=>{let r=c.getBoundingClientRect();return [r.left,r.top,r.width,r.height,c.querySelectorAll('b,small').length]})")
            if not chips: problems.append('[μπάρα παραθύρων] δεν υπάρχει κανένα κουμπί ελαχιστοποιημένου παραθύρου')
            for q in chips:
                if q[1] < bar[1] - 1 or q[1] + q[3] > bar[1] + bar[3] + 1 or q[0] < bar[0] - 1: problems.append('[μπάρα παραθύρων] κουμπί έξω από τη μπάρα κάτω αριστερά')
                if q[4] != 2: problems.append('[μπάρα παραθύρων] το κουμπί δεν έχει δύο γραμμές (τίτλος και προμηθευτής)')
            chips.sort(key=lambda t: t[0])
            for a_, c_ in zip(chips, chips[1:]):
                if c_[0] < a_[0] + a_[2] - 0.5: problems.append('[μπάρα παραθύρων] κουμπιά επικαλύπτονται')
        finally:
            b.close()
    for m in problems: print(m)
    return len(problems)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('ΠΡΟΒΛΗΜΑΤΑ ΠΑΡΑΘΥΡΩΝ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
