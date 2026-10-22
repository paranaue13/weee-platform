"""Έλεγχος πινάκων (τρέξε μετά από ΚΑΘΕ αλλαγή που αγγίζει πίνακες):
  python backend/scripts/check_tables.py [http://127.0.0.1:8000]
Για κάθε οθόνη/καρτέλα με πίνακα ελέγχει:
 1. sticky αριστερή στήλη: κανένα άλλο κελί δεν περνά από πάνω της στο οριζόντιο scroll
 2. sticky γραμμές συνόλων (tfoot): δεν επικαλύπτονται μεταξύ τους (η ορατότητα ΟΛΩΝ των γραμμών ελέγχεται στο check_tables_geometry.py)
 3. ο πίνακας γεμίζει τον διαθέσιμο χώρο (δεν μένει άδειος χώρος κάτω από τον πίνακα όταν το περιεχόμενο είναι μεγαλύτερο)
Τυπώνει ΜΟΝΟ προβλήματα. Μόνο ανάγνωση (login + πλοήγηση)."""
import sys
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding='utf-8')
B = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
JS = """()=>{let bad=[];const vh=innerHeight;
for(const t of document.querySelectorAll('table')){if(!t.offsetParent)continue;
 let w=t.parentElement;while(w&&!/auto|scroll/.test(getComputedStyle(w).overflowX+getComputedStyle(w).overflowY))w=w.parentElement;if(!w)continue;
 let name=(t.id||t.className||'table')+'';
 w.scrollLeft=w.scrollWidth;let wr=w.getBoundingClientRect();
 for(const c of t.querySelectorAll('th,td')){let cs=getComputedStyle(c);if(cs.position!=='sticky'||cs.left==='auto')continue;let r=c.getBoundingClientRect();
  if(r.width<5||r.top<wr.top||r.bottom>wr.bottom||r.bottom<0||r.top>vh)continue;let e=document.elementFromPoint(r.left+Math.min(r.width/2,20),r.top+r.height/2);
  if(e&&!c.contains(e)&&!e.closest('.topbar,.floatPanel,#toast,tfoot,thead')){bad.push(name+': στήλη κολλημένη αριστερά καλύπτεται από άλλο κελί ("'+c.innerText.slice(0,18)+'")');break}}
 let foot=[...t.querySelectorAll('tfoot tr')].filter(r=>(getComputedStyle(r.firstElementChild||r).position==='sticky'&&getComputedStyle(r.firstElementChild||r).bottom!=='auto'));
 if(foot.length){let tot=0,prev=null;for(const r of foot){let b=r.getBoundingClientRect();tot+=b.height;if(prev&&b.top<prev.bottom-1.5)bad.push(name+': γραμμές συνόλων επικαλύπτονται');prev=b}
  /* ΑΛΛΑΓΗ ΚΗ-2: το κάτω μπλοκ είναι ΠΑΝΤΑ ολόκληρο ορατό — ο παλιός περιορισμός «μισό ύψος» αφαιρέθηκε (η ορατότητα ελέγχεται στο check_tables_geometry.py) */}
 if(w.scrollHeight>w.clientHeight+2&&wr.bottom<vh-60&&!w.closest('.floatPanel,#floatingEditor,#receiptForm,#sortingDetail'))bad.push(name+': ο πίνακας δεν γεμίζει το παράθυρο (άδειο '+Math.round(vh-wr.bottom)+'px κάτω)');
}return [...new Set(bad)]}"""
with sync_playwright() as p:
    b = p.chromium.launch()
    try:
        pg = b.new_page(viewport={'width': 1366, 'height': 800})
        pg.goto(B + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
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
        print('ΠΡΟΒΛΗΜΑΤΑ:', total)
    finally:
        b.close()
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_tables_geometry
_g = check_tables_geometry.run(B); print('ΠΡΟΒΛΗΜΑΤΑ ΓΕΩΜΕΤΡΙΑΣ:', _g)
