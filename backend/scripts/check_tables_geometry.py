"""Έλεγχος γεωμετρίας πινάκων (τρέξε μετά από ΚΑΘΕ αλλαγή που αγγίζει πίνακες· τρέχει κι από το check_tables.py):
  python backend/scripts/check_tables_geometry.py [http://127.0.0.1:8000]
Για ΚΑΘΕ οθόνη/καρτέλα με πίνακα, σε στενό (700px), μεσαίο (1280px) και πλατύ (1900px) παράθυρο, zoom 100%, με οριζόντιο και κάθετο scroll
(αρχή / τέλος) ελέγχει:
 1. κάθε κελί της ίδιας γραμμής έχει την ίδια κάθετη θέση και το ίδιο ύψος (διαφορά ≤ 1px) -- πιάνει κολλημένα (sticky) κελιά που βγαίνουν από τη γραμμή τους
 2. δεν επικαλύπτονται κελιά διαφορετικών γραμμών της ΙΔΙΑΣ ενότητας (thead / tbody / tfoot)
 3. (ΑΛΛΑΓΗ ΚΓ, σε 1280x720 / 1600x900 / 1920x1080) το δεξί άκρο κάθε πίνακα = δεξί άκρο του πλαισίου του (κενό ≤1px)· στους πίνακες ανά ημέρα/μήνα (data-datefill)
    το κάτω άκρο του πλαισίου = κάτω άκρο της περιοχής περιεχομένου· και οι γραμμές συνόλων (tfoot) έχουν την ΙΔΙΑ θέση y για περίοδο με λίγες γραμμές και για περίοδο με πολλές
Τυπώνει ΜΟΝΟ προβλήματα. Μόνο ανάγνωση (login + πλοήγηση)· τα κελιά με rowspan και οι κρυμμένες στήλες εξαιρούνται."""
import sys
from playwright.sync_api import sync_playwright

from _browser import launch   # δικός μας browser, κλείνει μόνο με το handle του (ποτέ τερματισμός με όνομα εικόνας)
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
      cs.sort((a,b)=>a.r.top-b.r.top);   /* ταξινόμηση κατά ύψος: σταματά η σύγκριση όταν δεν υπάρχει πια κάθετη επικάλυψη (πριν: κάθε κελί με κάθε κελί, 80 δευτ. σε πίνακα 4.000 κελιών) */
      let n=0;
      for(let i=0;i<cs.length&&n<3;i++)for(let j=i+1;j<cs.length&&n<3;j++){if(cs[j].r.top>=cs[i].r.bottom-2)break;
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

JS_FILL = """()=>{const out=[];
 for(const t of document.querySelectorAll('table')){
  if(!t.offsetParent)continue;
  const w=t.closest('.prodTableWrap,.tablewrap');
  if(!w||t.closest('.floatPanel,#floatingEditor,#receiptForm,#sortingDetail,.repPop,.hidden'))continue;
  const name=(t.id||w.id||t.className||'table')+'';
  const wr=w.getBoundingClientRect(),tr=t.getBoundingClientRect();
  const zz=w.offsetWidth>0?wr.width/w.offsetWidth:1,gap=Math.round(wr.left+w.clientWidth*zz-tr.right);
  if(gap>1&&!t.dataset.cwGap)out.push(name+': ο πίνακας δεν γεμίζει το πλάτος του πλαισίου (κενό δεξιά '+gap+'px)');
  // ΑΛΛΑΓΗ ΚΣΤ: η τελευταία στήλη είναι κανονική στήλη (πλάτος, κάθετη γραμμή δεξιά, λαβή σύρσιμου)
  if(t.tHead){
   const leaf=[...t.tHead.querySelectorAll('th')].filter(th=>th.offsetParent&&th.colSpan===1&&!th.classList.contains('pinColHide'));
   if(leaf.length>=3){
    const lr=leaf.map(th=>th.getBoundingClientRect()),li=lr.reduce((m,r,i)=>r.right>lr[m].right?i:m,0),last=leaf[li],r=lr[li];
    let manual=false;try{manual=Object.keys(localStorage).some(k=>k.startsWith('colw:'))}catch(e){}
    const others=lr.filter((x,i)=>i!==li).map(x=>x.width),mx=Math.max(...others);
    if(!manual&&r.width>mx*1.6+1)out.push(name+': η τελευταία στήλη «'+last.textContent.trim().slice(0,20)+'» απλώνεται ('+Math.round(r.width)+'px, ενώ η φαρδύτερη άλλη είναι '+Math.round(mx)+'px)');
    const bw=th=>parseFloat(getComputedStyle(th).borderRightWidth)||0,hasV=leaf.filter((th,i)=>i!==li&&bw(th)>=1).length>leaf.length/2;
    if(hasV&&bw(last)<1)out.push(name+': η τελευταία στήλη «'+last.textContent.trim().slice(0,20)+'» δεν έχει κάθετη γραμμή δεξιά');
    if(!(t.dataset.cwGap)&&r.right<=wr.left+w.clientWidth+1&&last.dataset.wcol!=='stock'){
      const py=r.top+r.height*0.7,el=(py>=0&&py<innerHeight)?document.elementFromPoint(r.right-2,py):null;
      if(el&&el.closest('th')!==last)out.push(name+': η τελευταία στήλη «'+last.textContent.trim().slice(0,20)+'» δεν έχει λαβή σύρσιμου (το δεξί άκρο καλύπτεται)');
    }
   }
  }
  // επίπεδα κεφαλίδας: όλα τα κελιά του ίδιου επιπέδου (κατηγορία/υποκατηγορία = .thGroup, στήλες = leaf) έχουν το ίδιο background-color
  if(t.tHead&&t.classList.contains('prodTable')){
    const g=new Set(),l=new Set();
    t.tHead.querySelectorAll('th').forEach(th=>{if(!th.offsetParent||th.classList.contains('ovrCol'))return;(th.classList.contains('thGroup')?g:l).add(getComputedStyle(th).backgroundColor)});
    if(g.size>1)out.push(name+': κεφαλίδες κατηγορίας με διαφορετικό τόνο: '+[...g].join(' / '));
    if(l.size>1)out.push(name+': κεφαλίδες στηλών με διαφορετικό τόνο: '+[...l].join(' / '));
  }
  // sticky γραμμές συνόλων: όχι border-collapse:collapse
  if(t.tFoot&&[...t.tFoot.rows].some(r=>[...r.cells].some(c=>getComputedStyle(c).position==='sticky'))&&getComputedStyle(t).borderCollapse==='collapse')out.push(name+': sticky γραμμές συνόλων με border-collapse:collapse');
  if(t.hasAttribute('data-datefill')){
    const zb=document.getElementById('zoomBar'),exp=Math.max(wr.top+220,innerHeight-(zb?zb.offsetHeight:0));
    if(Math.abs(wr.bottom-exp)>3)out.push(name+': το πλαίσιο του πίνακα δεν φτάνει στο κάτω άκρο του διαθέσιμου χώρου ('+Math.round(wr.bottom)+'px αντί '+Math.round(exp)+'px)');
  }
 }
 return [...new Set(out)]}"""

# θέσεις y των γραμμών συνόλων (πρώτο κελί κάθε γραμμής tfoot, όπως φαίνονται -- τα κελιά είναι sticky)
JS_FOOT = """(sel)=>{const t=document.querySelector(sel);if(!t||!t.offsetParent||!t.tFoot)return null;return [...t.tFoot.rows].filter(r=>r.offsetParent&&r.cells.length).map(r=>Math.round(r.cells[0].getBoundingClientRect().top))}"""

# ΑΛΛΑΓΗ ΚΔ: το κάτω μπλοκ (tfoot) είναι πάντα ορατό μέσα στο πλαίσιο, μένει στην ίδια θέση πριν/μετά το scroll και τα ονόματα δεν κόβονται
JS_BLOCK = """()=>{window.scrollTo(0,document.documentElement.scrollHeight);const out=[];
for(const t of document.querySelectorAll('table.prodTable')){
 if(!t.offsetParent||!t.tFoot)continue;
 if(t.closest('.floatPanel,#floatingEditor,#receiptForm,#sortingDetail,.repPop'))continue;
 const w=t.closest('.prodTableWrap,.tablewrap');if(!w)continue;
 const rows=[...t.tFoot.rows].filter(r=>r.offsetParent&&r.cells.length);if(!rows.length)continue;
 const name=(t.id||w.id||(t.parentElement&&t.parentElement.id)||'πίνακας');
 const scrolls=w.scrollHeight>w.clientHeight+1;
 const tops=()=>rows.map(r=>Math.round(r.cells[0].getBoundingClientRect().top));
 const wr=w.getBoundingClientRect();
 // ονόματα που κόβονται (χωρίς tooltip)
 rows.forEach(r=>{const c=r.cells[0];if(c.scrollWidth>c.clientWidth+1&&!c.title)out.push('DEC0|'+name+': κομμένο όνομα γραμμής «'+c.textContent.trim()+'» χωρίς tooltip')});
 // ΑΛΛΑΓΗ ΚΗ-2: ΟΛΕΣ οι γραμμές του κάτω μπλοκ πρέπει να φαίνονται ολόκληρες: πάνω από την οριζόντια μπάρα του πλαισίου και πάνω από τη γραμμή κατάστασης
 const zb=document.getElementById('zoomBar'),barTop=zb?zb.getBoundingClientRect().top:innerHeight;
 const seeAll=(when)=>{const wq=w.getBoundingClientRect(),zz=w.offsetHeight>0?wq.height/w.offsetHeight:1,sb=Math.min(wq.top+w.clientTop*zz+w.clientHeight*zz,barTop);
   rows.forEach((r,i)=>{const bb=r.cells[0].getBoundingClientRect();if(bb.top<wq.top-1||bb.bottom>sb+1)out.push('DEC0|'+name+': η γραμμή «'+r.cells[0].textContent.trim().slice(0,28)+'» του κάτω μπλοκ κόβεται ('+when+')')})};
 seeAll('χωρίς scroll');
 if(!scrolls)continue;
 w.scrollTop=0;w.scrollLeft=0;const t0=tops();
 w.scrollTop=w.scrollHeight;w.scrollLeft=w.scrollWidth;const t1=tops();
 seeAll('μετά το scroll κάτω-δεξιά');
 if(t0.some((v,i)=>Math.abs(v-t1[i])>1))out.push('DEC0|'+name+': οι θέσεις των γραμμών μπλοκ αλλάζουν με το scroll '+t0+' → '+t1);
 w.scrollTop=0;w.scrollLeft=0;
}
window.scrollTo(0,0);return out}"""

FILL_SIZES = [(1280, 720), (1600, 900), (1920, 1080)]


def run_fill(base):
    """ΑΛΛΑΓΗ ΚΓ: πλήρες πλάτος / πλήρες ύψος / σταθερά σύνολα."""
    total = 0
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (W, H) in FILL_SIZES:
                pg = b.new_page(viewport={'width': W, 'height': H})
                pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                pg.evaluate("try{localStorage.setItem('invZoomPct','100')}catch(e){}")
                for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
                    pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1200)
                    pg.evaluate("""(()=>{try{if(typeof readyState!=='undefined'&&document.getElementById('ready')&&!document.getElementById('ready').classList.contains('hidden')){readyState.period='month';readyState.cursor=new Date('2026-09-15T12:00:00');readyRefreshActive()}}catch(e){}
                      try{if(typeof prodState!=='undefined'&&document.getElementById('production')&&!document.getElementById('production').classList.contains('hidden')){prodState.period='month';prodState.cursor=new Date('2026-09-15T12:00:00');loadProduction()}}catch(e){}})()""")
                    pg.wait_for_timeout(1500)
                    sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn,#{v} [data-lsub]"
                    n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
                    for i in range(n):
                        pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()")
                        pg.wait_for_timeout(1100)
                        # ανοιχτές κατηγορίες (έλεγχος τόνων κεφαλίδας σε πολυεπίπεδη κεφαλίδα)
                        pg.evaluate("document.querySelectorAll('.prodMajorHead[data-prodcat]:not(.expanded)').forEach((x,i)=>{if(i<2&&x.offsetParent)x.click()})"); pg.wait_for_timeout(600)
                        for msg in pg.evaluate(JS_FILL):
                            total += 1; print(f'[{W}x{H} · {v} / καρτέλα {i}] {msg}')
                        for msg in pg.evaluate(JS_BLOCK):
                            kind, txt = msg.split('|', 1)
                            total += 1; print(f'[{W}x{H} · {v} / καρτέλα {i}] ' + ('ΑΠΟΦΑΣΗ ΧΡΗΣΤΗ: ' if kind == 'DEC1' else '') + txt)
                # σταθερά σύνολα: ίδια θέση y για περίοδο με πολλές γραμμές (μήνας) και με λίγες (τρίμηνο = 3 γραμμές)
                for (view, tbl, setup) in (
                    ('production', '#productionWeeePanel table', "(p)=>{prodState.tab='weee';prodState.period=p;prodState.cursor=new Date('2026-09-15T12:00:00');loadProduction()}"),
                    ('ready', '#readyMatPanel table', "(p)=>{readyState.period=p;readyState.cursor=new Date('2026-09-15T12:00:00');readyRefreshActive()}")):
                    pg.evaluate(f"show('{view}')"); pg.wait_for_timeout(1200)
                    if view == 'production':
                        pg.evaluate("(()=>{let b=document.querySelector('.productionTab[data-prodtab=weee]');if(b)b.click()})()"); pg.wait_for_timeout(800)
                    pos = {}
                    for per in ('month', 'quarter', 'year'):
                        pg.evaluate(setup, per); pg.wait_for_timeout(2200)
                        pos[per] = pg.evaluate(JS_FOOT, tbl)
                    base_pos = pos.get('month')
                    for per in ('quarter', 'year'):
                        if base_pos and pos[per] and (len(base_pos) != len(pos[per]) or any(abs(a - b2) > 1 for a, b2 in zip(base_pos, pos[per]))):
                            total += 1; print(f'[{W}x{H} · {view}] γραμμές συνόλων: διαφορετική θέση y για περίοδο «{per}» {pos[per]} και «μήνας» {base_pos}')
                pg.close()
        finally:
            b.close()
    return total


# ΑΛΛΑΓΗ ΚΖ: ποσοστό μεγέθους 70% / 100% / 150% — ο πίνακας γεμίζει το πλάτος, φτάνει στη γραμμή κατάστασης, το κάτω μπλοκ μένει ορατό
JS_ZOOM = """()=>{window.scrollTo(0,document.documentElement.scrollHeight);const out=[],zb=document.getElementById('zoomBar');if(!zb)return ['δεν υπάρχει γραμμή κατάστασης (#zoomBar)'];
 const bar=zb.getBoundingClientRect();
 if(Math.abs(bar.bottom-innerHeight)>1)out.push('η γραμμή κατάστασης δεν είναι κάτω-κάτω ('+Math.round(bar.bottom)+' αντί '+innerHeight+')');
 for(const w of document.querySelectorAll('.prodTableWrap')){
  if(!w.offsetParent||!w.closest('.content>.view'))continue;
  const t=w.querySelector('table.prodTable');if(!t||!t.offsetParent)continue;
  const wr=w.getBoundingClientRect(),tr=t.getBoundingClientRect(),name=(t.id||w.id||t.className||'πίνακας')+'';
  if(wr.height<120)continue;
  if(w.scrollWidth<=w.clientWidth+1&&Math.abs(wr.right-1-tr.right)>1.5)out.push(name+': δεν γεμίζει το πλάτος (διαφορά '+Math.round(wr.right-1-tr.right)+'px)');
  if(t.hasAttribute('data-datefill')||w.id==='invTableWrap'){const g=bar.top-wr.bottom;if(g>3||g<-1)out.push(name+': το πλαίσιο δεν φτάνει στη γραμμή κατάστασης (κενό '+Math.round(g)+'px)')}
  if(wr.bottom>bar.top+1)out.push(name+': το πλαίσιο καλύπτεται από τη γραμμή κατάστασης');
 }
 window.scrollTo(0,0);return out}"""

ZOOMS = [70, 100, 150]


ZOOM_SIZES = [(1280, 720), (1920, 1080)]
READY_TABS = ['AXIOPOIISIMA', 'EIDIKIS_DIACHEIRISIS', 'PLAKETES', 'APORRIPSI', 'PRESS', 'WAREHOUSE']


def run_zoom(base):
    total = 0
    cfgs = [('inventory', 'Απογραφή', None)]
    cfgs += [('production', 'Παραγωγή/' + t, f"(()=>{{let b=document.querySelector('.productionTab[data-prodtab={t}]');if(b)b.click()}})()") for t in ('weee', 'people', 'deltio')]
    cfgs += [('ready', 'Υλικά/' + t, f"(()=>{{let b=[...document.querySelectorAll('#ready .readyGroupTab')].find(x=>x.dataset.readygroup==='{t}');if(b)b.click()}})()") for t in READY_TABS]
    cfgs += [('loading', 'Φορτώσεις/ιστορικό', "(()=>{let b=document.querySelector('[data-lsub=hist]');if(b)b.click()})()")]
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (W, H) in ZOOM_SIZES:
                pg = b.new_page(viewport={'width': W, 'height': H})
                pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                pg.evaluate("try{localStorage.clear()}catch(e){}"); pg.reload(wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                for (view, label, tab) in cfgs:
                    pg.evaluate(f"show('{view}')"); pg.wait_for_timeout(1000)
                    if tab: pg.evaluate(tab); pg.wait_for_timeout(1100)
                    for z in ZOOMS:
                        pg.evaluate(f"setViewZoom({z})"); pg.wait_for_timeout(900)
                        for msg in pg.evaluate(JS_ZOOM):
                            total += 1; print(f'[{W}x{H} · zoom {z}% · {label}] {msg}')
                        for msg in pg.evaluate(JS_BLOCK):
                            kind, txt = msg.split('|', 1)
                            total += 1; print(f'[{W}x{H} · zoom {z}% · {label}] ' + txt)
                    pg.evaluate("setViewZoom(100)")
                pg.close()
        finally:
            b.close()
    return total


SIZES = [(700, 800), (1280, 800), (1900, 1000)]


def run(base='http://127.0.0.1:8000'):
    total = 0
    with sync_playwright() as p:
        b = launch(p)
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
    total += run_fill(base)
    total += run_zoom(base)
    return total


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
    n = run(base)
    print('ΠΡΟΒΛΗΜΑΤΑ ΓΕΩΜΕΤΡΙΑΣ:', n)
    sys.exit(1 if n else 0)
