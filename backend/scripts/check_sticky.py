"""ΚΑΝΟΝΑΣ ΚΘ — Πίνακες και λίστες με scroll: σταθερά τμήματα.

Ανοίγει κάθε σελίδα/καρτέλα, αντιπροσωπευτικά παράθυρα (modals) και dropdown/λίστες επιλογής, βρίσκει ΚΑΘΕ στοιχείο που κάνει scroll
και ελέγχει, αφού κάνει scroll στο τέλος / στη μέση:
  (α) κεφαλίδα στηλών πίνακα: sticky και ορατή πάνω-πάνω (δεν την καλύπτει τίποτα)
  (β) γραμμές συνόλων (tfoot): ορατές κάτω-κάτω (και στην αρχή του scroll)
  (γ) τίτλοι ομάδων/κατηγοριών λιστών: sticky, ορατοί και όχι κομμένοι
Τυπώνει πίνακα «Σημείο | Σταθερή κεφαλίδα | Σταθερά σύνολα» και ΑΠΟΤΥΓΧΑΝΕΙ (επιστρέφει >0 προβλήματα) αν κάτι δεν πληρούν τον κανόνα.
Μόνο ανάγνωση (login + πλοήγηση). Ο browser ανοίγει/κλείνει μόνο μέσω backend/scripts/_browser.py.
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch

# ---- σαρωτής: μία κλήση ανά «σημείο» (σελίδα/καρτέλα/παράθυρο/dropdown) ----
JS_SCAN = r"""([label,rootSel])=>{
 const ROOT=rootSel?document.querySelector(rootSel):document;if(!ROOT)return [];
 const out=[];
 const HEAD_SEL='.prepCat,.sfG,.sfTh,.cgHead,.sfHd,.whCat,.comboSec,.cpTitle,.ovTblHead,.thGroup';
 const vis=e=>{const r=e.getBoundingClientRect();if(r.width<30||r.height<30)return false;for(let p=e;p&&p!==document.body;p=p.parentElement){const cs=getComputedStyle(p);if(cs.display==='none'||cs.visibility==='hidden')return false}return true};
 const scrolls=e=>{const cs=getComputedStyle(e);return /(auto|scroll)/.test(cs.overflowY)};
 const nearest=e=>{for(let p=e.parentElement;p&&p!==document.body&&p!==document.documentElement;p=p.parentElement)if(scrolls(p))return p;return null};
 const desc=e=>{let id=e.id?'#'+e.id:'';let c=(e.className&&e.className.baseVal===undefined?String(e.className):'').trim().split(/\s+/).slice(0,2).join('.');return e.tagName.toLowerCase()+id+(c?'.'+c:'')};
 const coverEl=(el)=>{const r=el.getBoundingClientRect();const x=r.left+Math.min(r.width/2,60),y=r.top+r.height/2;return document.elementFromPoint(x,y)};
 const cover=(el)=>{const t=coverEl(el);return !!t&&(el===t||el.contains(t))};
 const list=(ROOT===document?[...document.querySelectorAll('*')]:[ROOT,...ROOT.querySelectorAll('*')]).filter(e=>!['TEXTAREA','SELECT','INPUT','HTML','BODY'].includes(e.tagName)&&scrolls(e)&&e.scrollHeight>e.clientHeight+3&&e.clientHeight>=40&&vis(e));
 for(const el of list){
  const tabs=[...el.querySelectorAll('table')].filter(t=>nearest(t)===el&&t.offsetParent!==null&&t.rows.length>0);
  const heads=[...el.querySelectorAll(HEAD_SEL+',tr.stkGroupRow')].filter(h=>nearest(h)===el&&h.offsetParent!==null).map(h=>h.tagName==='TR'?h.cells[0]:h).filter(Boolean);
  const items=[...el.children].length;
  if(!tabs.length&&!heads.length&&items<5)continue;           // όχι πίνακας/λίστα
  const st0=el.scrollTop,wy=window.scrollY;
  if(getComputedStyle(el).position!=='fixed'&&!el.closest('.sortingPopup,#floatingEditor,.comboMenu,.sfDD'))el.scrollIntoView({block:'center'});   // ο έλεγχος κάνει elementFromPoint: το στοιχείο πρέπει να είναι μέσα στο ορατό τμήμα του παραθύρου
  const rec={label,sel:desc(el),kind:tabs.length?'πίνακας':(heads.length?'λίστα με τίτλους':'λίστα'),head:null,foot:null,notes:[]};
  const er=()=>{const r=el.getBoundingClientRect();return {top:r.top+el.clientTop,bottom:r.top+el.clientTop+el.clientHeight}};
  // --- πίνακες ---
  for(const t of tabs){
    const nm=desc(t);
    if(t.tHead&&t.tHead.rows.length){
      const cells=[...t.tHead.rows[0].cells].filter(c=>c.offsetParent!==null);
      if(!cells.length)continue;
      const probes=tabs.length>1?[0.3,0.6,1]:[1];
      for(const f of probes){
      el.scrollTop=Math.round((el.scrollHeight-el.clientHeight)*f);const e=er();
      const tr0=t.getBoundingClientRect();
      if(tabs.length>1&&(tr0.top>=e.top+4||tr0.bottom<=e.top+cells[0].getBoundingClientRect().height*3+8))continue;   // ο πίνακας δεν βρίσκεται «κάτω από την κορυφή»: δεν χρειάζεται καρφωμένη κεφαλίδα
      const th=cells.find(c=>c.getBoundingClientRect().width>8)||cells[0],r=th.getBoundingClientRect(),pos=getComputedStyle(th).position;
      const okPos=pos==='sticky',okPlace=r.top>=e.top-2&&r.top<=e.top+280&&r.bottom<=e.bottom,okCover=cover(th);
      const ok=okPos&&okPlace&&okCover;
      rec.head=(rec.head===false)?false:ok;
      if(!ok){const m=nm+': κεφαλίδα '+(okPos?'':'ΔΕΝ είναι sticky; ')+(okPlace?'':'εκτός θέσης; ')+(okCover?'':'καλύπτεται από '+desc(coverEl(th)||document.body));if(!rec.notes.includes(m))rec.notes.push(m)}
      }
      el.scrollTop=st0;
    }
    if(t.tFoot&&t.tFoot.rows.length){
      const rows=[...t.tFoot.rows].filter(r=>r.offsetParent!==null&&r.cells.length);
      if(rows.length){
        el.scrollTop=0;const e=er();let ok=true,why='';
        for(const r of rows){const c=r.cells[0],b=c.getBoundingClientRect();
          if(b.bottom>e.bottom+1||b.top<e.top){ok=false;why='γραμμή «'+c.textContent.trim().slice(0,24)+'» εκτός ορατού τμήματος στην αρχή του scroll';break}
          if(getComputedStyle(c).position!=='sticky'&&el.scrollHeight>el.clientHeight+3){ok=false;why='γραμμή «'+c.textContent.trim().slice(0,24)+'» δεν είναι sticky';break}}
        if(ok){el.scrollTop=el.scrollHeight;const e2=er();for(const r of rows){const b=r.cells[0].getBoundingClientRect();if(b.bottom>e2.bottom+1||b.top<e2.top){ok=false;why='γραμμή «'+r.cells[0].textContent.trim().slice(0,24)+'» κόβεται στο τέλος';break}}}
        rec.foot=(rec.foot===false)?false:ok;if(!ok)rec.notes.push(desc(t)+': σύνολα: '+why);
        el.scrollTop=st0;
      }
    }
  }
  // --- τίτλοι ομάδων/λιστών ---
  if(heads.length){
    const maxS=el.scrollHeight-el.clientHeight;let ok=true,why='';
    const nonSticky=heads.filter(h=>getComputedStyle(h).position!=='sticky');
    if(nonSticky.length===heads.length){ok=false;why='οι τίτλοι δεν είναι sticky ('+desc(heads[0])+')'}
    else{
      const probe=[0.35,0.7,1];
      for(const f of probe){el.scrollTop=Math.round(maxS*f);const e=er();
        const pinned=heads.filter(h=>getComputedStyle(h).position==='sticky').filter(h=>{const r=h.getBoundingClientRect();return r.top>=e.top-1&&r.top<=e.top+280&&r.bottom<=e.bottom});
        const topOne=pinned.find(h=>cover(h));
        // κομμένος τίτλος: οριζόντια ή κάθετα
        const cut=heads.find(h=>{const r=h.getBoundingClientRect();return r.bottom>e.top&&r.top<e.bottom&&h.scrollWidth>h.clientWidth+2});
        if(!topOne&&el.scrollTop>40){ok=false;why='ο τίτλος ομάδας δεν μένει ορατός στο scroll ('+Math.round(f*100)+'%)';break}
        if(cut){ok=false;why='τίτλος «'+cut.textContent.trim().slice(0,30)+'» κόβεται οριζόντια';break}
      }
    }
    rec.head=(rec.head===false)?false:ok;if(!ok)rec.notes.push(why);
    el.scrollTop=st0;
  }
  // φόντο διαφανές σε sticky κελιά/τίτλους (φαίνονται οι γραμμές από κάτω)
  const stk=[...el.querySelectorAll('th,td,'+HEAD_SEL)].filter(x=>nearest(x)===el&&getComputedStyle(x).position==='sticky').slice(0,400);
  const transp=stk.find(x=>{const bg=getComputedStyle(x).backgroundColor;return bg==='rgba(0, 0, 0, 0)'||bg==='transparent'});
  if(transp){rec.head=false;rec.notes.push('sticky στοιχείο με διαφανές φόντο ('+desc(transp)+')')}
  if(rec.head===null&&tabs.length&&tabs.every(t=>!t.tHead||[...t.tHead.rows[0].cells].every(c=>getComputedStyle(c).position==='sticky')))rec.head=tabs.some(t=>t.tHead)?true:null;   // πολλοί πίνακες στο ίδιο scroll: κάθε κεφαλίδα είναι sticky μέσα στον πίνακά της
  window.scrollTo(0,wy);
  out.push(rec);
 }
 return out}"""


def _row(rec):
    def mark(v, none='—'):
        return none if v is None else ('✓' if v else '✗')
    return f"| {rec['label']} · {rec['sel']} ({rec['kind']}) | {mark(rec['head'])} | {mark(rec['foot'])} |"


def run_sticky(base, print_table=True, size=(1600, 900)):
    """Επιστρέφει πλήθος προβλημάτων· τυπώνει τον πίνακα και τα σημεία που δεν πληρούν τον κανόνα."""
    results = []
    with sync_playwright() as p:
        b = launch(p)
        try:
            pg = b.new_page(viewport={'width': size[0], 'height': size[1]})
            pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
            pg.evaluate("try{localStorage.clear()}catch(e){}"); pg.reload(wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
            pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)

            def scan(label, root=None):
                for r in pg.evaluate(JS_SCAN, [label, root]):
                    results.append(r)

            # ---- σελίδες / καρτέλες ----
            for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
                pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1200)
                sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn,#{v} [data-lsub]"
                n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
                for i in range(min(n, 8)):
                    pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()")
                    pg.wait_for_timeout(1100)
                    name = pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);return l[{i}]?l[{i}].textContent.trim().slice(0,22):''}})()")
                    scan(f'Σελίδα {v} › {name or i}')

            # ---- παράθυρο Ταξινόμησης + dropdown μέσου συλλογής ----
            ld = pg.evaluate("async()=>{let q=await api('/sorting/review-queue');let r=q.find(x=>['READY_FOR_SORTING','SORTING_IN_PROGRESS'].includes(x.status));return r?{id:r.load_id,day:r.receipt_date.slice(0,10)}:null}")
            if ld:
                pg.evaluate("document.querySelector('.nav button[data-view=\"receipts\"]').click()"); pg.wait_for_timeout(1000)
                pg.evaluate("(d)=>{receiptNav.day=d;receiptNav.year=+d.slice(0,4);receiptNav.month=+d.slice(5,7);receiptCalCursor=new Date(receiptNav.year,receiptNav.month-1,1);loadReceiptsV2()}", ld['day']); pg.wait_for_timeout(2000)
                pg.evaluate("(id)=>openSortingDetail(id)", ld['id']); pg.wait_for_timeout(2600)
                scan('Παράθυρο Ταξινόμησης › Καταχώρηση ανά κατηγορία ΑΗΗΕ','#sortingDetail')
                # η κεφαλίδα του παραθύρου αλλάζει ύψος μετά το άνοιγμα (μήνυμα / αναδίπλωση κουμπιών): η κεφαλίδα του πίνακα πρέπει να ακολουθεί
                pg.evaluate("(()=>{let h=document.querySelector('#sortingDetail .sortingPopupHeader');if(h&&!document.getElementById('tmpHdGrow'))h.insertAdjacentHTML('beforeend','<div id=\"tmpHdGrow\" style=\"height:44px\"></div>')})()"); pg.wait_for_timeout(600)
                scan('Παράθυρο Ταξινόμησης › με ψηλότερη κεφαλίδα παραθύρου (+44px)','#sortingDetail')
                pg.evaluate("(()=>{let e=document.getElementById('tmpHdGrow');if(e)e.remove()})()"); pg.wait_for_timeout(300)
                pg.evaluate("(()=>{const i=document.querySelector('#sfList .sfM');if(i){i.scrollIntoView({block:'center'});i.focus()}})()"); pg.wait_for_timeout(900)
                scan('Dropdown › Μέσο συλλογής (Ταξινόμηση)','.sfDD')
                pg.evaluate("document.activeElement&&document.activeElement.blur();document.querySelectorAll('.sfDD').forEach(e=>e.remove())")
                pg.evaluate("(()=>{let s=document.getElementById('sortingDetail');if(s)s.classList.add('hidden')})()")

            # ---- Νέα παραλαβή + combo ----
            pg.evaluate("show('receipts')"); pg.wait_for_timeout(800)
            pg.evaluate("(()=>{let b=document.getElementById('receiptDaysMode');if(b)b.click()})()"); pg.wait_for_timeout(800)
            if pg.evaluate("!!document.getElementById('newReceipt')"):
                pg.evaluate("(()=>{let b=document.getElementById('newReceipt');b.classList.remove('hidden');b.click()})()"); pg.wait_for_timeout(1500)
                scan('Παράθυρο › Νέα παραλαβή','#receiptBody')
                pg.evaluate("(()=>{const i=document.getElementById('carrierText');if(i){i.focus();i.click()}})()"); pg.wait_for_timeout(700)
                scan('Dropdown › Μεταφορέας (Νέα παραλαβή)','.comboMenu:not(.hidden)')
                pg.keyboard.press('Escape')
                pg.evaluate("document.querySelectorAll('.comboMenu').forEach(e=>e.classList.add('hidden'));let f=document.getElementById('floatingEditor');if(f)f.classList.add('hidden');(()=>{let b=document.getElementById('closeReceiptTop');if(b)b.click()})()");pg.wait_for_timeout(500)

            # ---- Φορτώσεις › Προετοιμασία: λίστες Αποθήκη / Φορτίο ----
            pg.evaluate("show('loading')"); pg.wait_for_timeout(1000)
            pg.evaluate("(()=>{let b=document.querySelector('[data-lsub=prep]');if(b)b.click()})()"); pg.wait_for_timeout(1800)
            scan('Φορτώσεις › Προετοιμασία (Αποθήκη / Φορτίο)','#prepPanel')

            # ---- Αναφορές / Υλικά: παράθυρα ----
            pg.evaluate("show('ready')"); pg.wait_for_timeout(1200)
            for (lbl, js) in (
                ('Παράθυρο › Εξαγωγή υλικών', "(()=>{let b=[...document.querySelectorAll('#ready button')].find(x=>/Εξαγωγή υλικών/.test(x.textContent));if(b)b.click()})()"),
                ('Παράθυρο › Ιστορικό διορθώσεων υλικών', "(()=>{if(typeof readyCorrHistory==='function'&&(readyState.corrections||[]).length)readyCorrHistory(readyState.corrections)})()"),
            ):
                pg.evaluate(js); pg.wait_for_timeout(1200)
                scan(lbl,'#floatingEditor')
                pg.evaluate("let f=document.getElementById('floatingEditor');if(f)f.classList.add('hidden')")
            pg.evaluate("show('reports')"); pg.wait_for_timeout(800)
        finally:
            b.close()

    # ---- ενοποίηση ανά σημείο ----
    problems = []
    seen = {}
    for r in results:
        k = (r['label'], r['sel'])
        if k in seen:                       # ίδιο στοιχείο ξανά (π.χ. άλλη καρτέλα ίδιου πίνακα)
            o = seen[k]
            for f in ('head', 'foot'):
                if r[f] is False: o[f] = False
                elif o[f] is None: o[f] = r[f]
            o['notes'] += [n for n in r['notes'] if n not in o['notes']]
        else:
            seen[k] = dict(r)
    rows = list(seen.values())
    if print_table:
        print('| Σημείο | Έχει σταθερή κεφαλίδα; | Έχει σταθερά σύνολα; |')
        print('|---|---|---|')
        for r in rows:
            print(_row(r))
        print()
    for r in rows:
        if r['head'] is False or r['foot'] is False:
            for n in r['notes'] or ['δεν πληρούται ο κανόνας']:
                problems.append(f"{r['label']} · {r['sel']}: {n}")
    for t in problems:
        print(f'ΔΕΝ ΠΛΗΡΟΥΝ ΤΟΝ ΚΑΝΟΝΑ ΚΘ [{size[0]}x{size[1]}] ·', t)
    print(f'ΠΡΟΒΛΗΜΑΤΑ ΣΤΑΘΕΡΩΝ ΤΜΗΜΑΤΩΝ [{size[0]}x{size[1]}]: {len(problems)}')
    return len(problems)


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
    n = run_sticky(base, True, (1600, 900)) + run_sticky(base, False, (1280, 720))
    sys.exit(1 if n else 0)
