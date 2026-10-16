"""Έλεγχος γεωμετρίας πινάκων (τρέξε μετά από ΚΑΘΕ αλλαγή που αγγίζει πίνακες· τρέχει κι από το check_tables.py):
  python backend/scripts/check_tables_geometry.py [http://127.0.0.1:8000]
Για ΚΑΘΕ οθόνη/καρτέλα με πίνακα, σε στενό (700px), μεσαίο (1280px) και πλατύ (1900px) παράθυρο, zoom 100%, με οριζόντιο και κάθετο scroll
(αρχή / τέλος) ελέγχει:
 1. κάθε κελί της ίδιας γραμμής έχει την ίδια κάθετη θέση και το ίδιο ύψος (διαφορά ≤ 1px) -- πιάνει κολλημένα (sticky) κελιά που βγαίνουν από τη γραμμή τους
 2. δεν επικαλύπτονται κελιά διαφορετικών γραμμών της ΙΔΙΑΣ ενότητας (thead / tbody / tfoot)
Τυπώνει ΜΟΝΟ προβλήματα. Μόνο ανάγνωση (login + πλοήγηση)· τα κελιά με rowspan και οι κρυμμένες στήλες εξαιρούνται."""
import sys
from playwright.sync_api import sync_playwright

JS = """()=>{
const out=[];const R=c=>c.getBoundingClientRect();
const vst=c=>{const k=getComputedStyle(c);return k.position==='sticky'&&(k.bottom!=='auto'||k.top!=='auto')};
for(const t of document.querySelectorAll('table')){
  if(!t.offsetParent||t.rows.length<2)continue;
  if(t.closest('.floatPanel,#floatingEditor,#receiptForm,#sortingDetail,.hidden'))continue;
  const name=(t.id||t.parentElement.id||t.className||'table')+'';
  let w=t.parentElement;while(w&&w!==document.body&&!/auto|scroll/.test(getComputedStyle(w).overflowX+getComputedStyle(w).overflowY))w=w.parentElement;
  const rows=[...t.rows].filter(r=>r.offsetParent&&r.cells.length&&!r.classList.contains('pinRowHide'));
  const states=w&&w!==document.body?[[0,0],[1,0],[1,1],[0,1]]:[[0,0]];
  for(const [sx,sy] of states){
    if(w&&w!==document.body){w.scrollLeft=sx?w.scrollWidth:0;w.scrollTop=sy?w.scrollHeight:0}
    const where=name+(w&&w!==document.body?' (scroll '+(sx?'→':'←')+(sy?'↓':'↑')+')':'');
    // 1) ίδια κάθετη θέση/ύψος μέσα στη γραμμή
    rows.forEach((tr,ri)=>{
      const cells=[...tr.cells].filter(c=>c.offsetParent&&c.rowSpan===1&&!c.classList.contains('pinColHide')&&R(c).width>1);
      if(cells.length<2)return;
      const tops=cells.map(c=>R(c).top).sort((a,b)=>a-b),hs=cells.map(c=>R(c).height).sort((a,b)=>a-b);
      const mt=tops[tops.length>>1],mh=hs[hs.length>>1];
      cells.forEach(c=>{const r=R(c);if(Math.abs(r.top-mt)>1||Math.abs(r.height-mh)>1)out.push(where+': κελί «'+(c.textContent||'').trim().slice(0,24)+'» (γραμμή '+(ri+1)+', '+tr.parentElement.tagName.toLowerCase()+', '+getComputedStyle(c).position+') εκτός γραμμής: κάθετη διαφορά '+Math.round(r.top-mt)+'px, ύψος '+Math.round(r.height-mh)+'px')});
    });
    // 2) επικαλύψεις μέσα στην ίδια ενότητα
    for(const sec of [t.tHead,...t.tBodies,t.tFoot].filter(Boolean)){
      const cs=[];[...sec.rows].forEach((tr,ri)=>{if(!tr.offsetParent)return;[...tr.cells].forEach(c=>{if(c.offsetParent&&c.rowSpan===1&&c.colSpan===1&&!c.classList.contains('pinColHide')){const r=R(c);if(r.width>2&&r.height>2)cs.push({ri,c,r})}})});
      let n=0;
      for(let i=0;i<cs.length&&n<3;i++)for(let j=i+1;j<cs.length&&n<3;j++){
        const a=cs[i],b=cs[j];if(a.ri===b.ri)continue;
        // κολλημένο κάθετα (π.χ. σύνολα στο κάτω μέρος) πάνω από μη κολλημένο = σκόπιμη επικάλυψη (κυλάνε από κάτω)· ελέγχονται μόνο ομοειδή ζεύγη
        if(vst(a.c)!==vst(b.c))continue;
        const ox=Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left),oy=Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top);
        if(ox>2&&oy>2){out.push(where+': επικάλυψη κελιών «'+(a.c.textContent||'').trim().slice(0,16)+'» / «'+(b.c.textContent||'').trim().slice(0,16)+'» ('+sec.tagName.toLowerCase()+')');n++}
      }
    }
  }
  if(w&&w!==document.body){w.scrollLeft=0;w.scrollTop=0}
}
return [...new Set(out)]}"""

SIZES = [(700, 800), (1280, 800), (1900, 1000)]


def run(base='http://127.0.0.1:8000'):
    total = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            for (W, H) in SIZES:
                pg = b.new_page(viewport={'width': W, 'height': H})
                pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                pg.evaluate("try{localStorage.setItem('invZoomPct','100')}catch(e){}")
                for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
                    pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1500)
                    # περίοδος με δεδομένα όπου υπάρχει (Υλικά / Παραγωγή): ο πίνακας πρέπει να έχει γραμμές για να ελεγχθεί
                    pg.evaluate("""(()=>{try{if(typeof readyState!=='undefined'&&document.getElementById('ready')&&!document.getElementById('ready').classList.contains('hidden')){readyState.period='month';readyState.cursor=new Date('2026-09-15T12:00:00');readyRefreshActive()}}catch(e){}
                      try{if(typeof prodState!=='undefined'&&document.getElementById('production')&&!document.getElementById('production').classList.contains('hidden')){prodState.cursor=new Date('2026-09-15T12:00:00');loadProduction()}}catch(e){}})()""")
                    pg.wait_for_timeout(1500)
                    sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn,#{v} [data-lsub]"
                    n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
                    for i in range(n):
                        pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()")
                        pg.wait_for_timeout(1200)
                        # ξανά μηνύματα δεδομένων μετά την αλλαγή καρτέλας (Υλικά)
                        for msg in pg.evaluate(JS):
                            total += 1; print(f'[{W}x{H} · {v} / καρτέλα {i}] {msg}')
                pg.close()
        finally:
            b.close()
    return total


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
    n = run(base)
    print('ΠΡΟΒΛΗΜΑΤΑ ΓΕΩΜΕΤΡΙΑΣ:', n)
    sys.exit(1 if n else 0)
