"""Έλεγχος «πηδήματος» πινάκων στην αυτόματη ανανέωση (τρέξε μετά από ΚΑΘΕ αλλαγή που αγγίζει πίνακα/σελίδα/καρτέλα):
  python backend/scripts/check_refresh_jump.py [http://127.0.0.1:8000]
Για κάθε οθόνη/καρτέλα με πίνακα που έχει σύνολα (tfoot) ξαναγράφει το σώμα του πίνακα με το ΙΔΙΟ περιεχόμενο (όπως η αυτόματη ανανέωση)
και μετρά τη θέση των συνόλων σε κάθε καρέ: αν σε ΟΠΟΙΟΔΗΠΟΤΕ καρέ αλλάξει (>1px) = ο πίνακας «σπάει» για λίγο → αποτυχία.
Τυπώνει ΜΟΝΟ προβλήματα. Μόνο ανάγνωση (login + πλοήγηση· τα δεδομένα δεν αλλάζουν — αλλάζει μόνο το DOM της σελίδας)."""
import sys
from playwright.sync_api import sync_playwright
from _browser import launch
sys.stdout.reconfigure(encoding='utf-8')
B = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
JS = """async()=>{let bad=[];
for(const t of document.querySelectorAll('table')){if(!t.offsetParent||!t.tFoot||!t.tBodies[0]||!t.tFoot.rows.length)continue;
 const tb=t.tBodies[0],name=(t.id||t.className||'table')+'';
 const top=()=>Math.round(t.tFoot.rows[0].getBoundingClientRect().top);
 await new Promise(r=>setTimeout(r,400));      // να σταθεροποιηθεί η διάταξη πριν τη μέτρηση
 let tops=[top()];
 await new Promise(res=>{let n=0;const f=()=>{n++;tops.push(top());if(n===2){tb.innerHTML=tb.innerHTML;tops.push(top())}if(n<14)requestAnimationFrame(f);else res()};requestAnimationFrame(f)});
 let mn=Math.min(...tops),mx=Math.max(...tops);if(mx-mn>1)bad.push(name+': τα σύνολα «πήδησαν» '+(mx-mn)+'px κατά την ανανέωση ('+mn+'..'+mx+')')}
return bad}"""
with sync_playwright() as p:
    b = launch(p)
    try:
        pg = b.new_page(viewport={'width': 1366, 'height': 800})
        pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)', timeout=20000)
        total = 0
        for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
            pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1500)
            sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn"
            n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
            for i in range(n):
                if n > 1 or pg.evaluate(f"document.querySelectorAll('{sel}').length"):
                    pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()"); pg.wait_for_timeout(1200)
                for msg in pg.evaluate(JS):
                    total += 1; print(f'[{v} / καρτέλα {i}] {msg}')
        print('OK: κανένα πήδημα' if not total else f'ΣΥΝΟΛΟ προβλημάτων: {total}')
    finally:
        b.close()
