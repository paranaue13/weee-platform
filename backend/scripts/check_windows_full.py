"""Πλήρης έλεγχος ΟΛΩΝ των παραθύρων (Windows) με πραγματικά screenshots.
Κάθε παράθυρο ανοίγει με πραγματικά δεδομένα (αντίγραφο βάσης), σε κάθε καρτέλα του, σε 4 καταστάσεις (μικρό / κανονικό / μεγάλο / μεγιστοποίηση)
και ζουμ οθόνης 100 / 125 / 150 %. Ελέγχει: μέσα στα όρια της οθόνης, στοιχεία έξω από το παράθυρο, οριζόντια υπερχείλιση εκτός από πλαίσια πινάκων,
κομμένα κείμενα χωρίς tooltip, γραμμές καρτελών που δεν φτάνουν στην άκρη, κεφαλίδα πίνακα στενότερη από τις γραμμές του.
Τυπώνει μόνο προβλήματα και τη λίστα των παραθύρων. Μόνο ανάγνωση (ανοίγει/κλείνει παράθυρα, δεν αποθηκεύει).
Χρήση (ΜΟΝΟ σε server με αντίγραφο δεδομένων): python check_windows_full.py http://127.0.0.1:8024 <φάκελος screenshots> [γρήγορο]"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
from check_visual import LINES_JS

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000').rstrip('/')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get('TEMP', '.'), 'check_windows_full')
QUICK = len(sys.argv) > 3
ZOOMS = [1, 1.5] if QUICK else [1, 1.25, 1.5]
VIEW = (1600, 950)

WINSEL = "#floatingEditor:not(.hidden),#receiptForm:not(.hidden),#sortingDetail:not(.hidden),#stockModal:not(.hidden)>*,#stockModal:not(.hidden),.repPop,.drpPop:not(.hidden)"
FIND = r"""(sel)=>{document.querySelectorAll('[data-cw]').forEach(x=>x.removeAttribute('data-cw'));
 const ok=e=>{if(!e)return false;const cs=getComputedStyle(e),r=e.getBoundingClientRect();return !e.classList.contains('hidden')&&!e.classList.contains('popupMin')&&cs.display!=='none'&&/fixed|absolute/.test(cs.position)&&r.width>200&&r.height>60};
 const pri=['#sortingDetail','#receiptForm','#floatingEditor'].map(q=>document.querySelector(q)).filter(ok);
 const pop=[...document.querySelectorAll('.repPop,.drpPop')].filter(ok);
 const w=pop[0]||pri[0];window.__cw=w||null;if(!w)return null;w.setAttribute('data-cw','1');return w.id||w.className}"""
# ο «πίνακας» του #stockModal είναι το εσωτερικό κουτί
STATE = r"""([st,vw,vh])=>{let w=window.__cw;if(!w)return 'no window';
 const ctl=[...w.querySelectorAll('.winCtl,[data-win]')];const max=ctl.find(b=>b.dataset.win==='max')||ctl[1];
 if(w.classList.contains('popupMax')&&max&&st!=='max')max.click();
 if(st==='small'){w.style.width=Math.min(520,vw-40)+'px';w.style.height=Math.min(440,vh-60)+'px'}
 else if(st==='large'){w.style.width=(vw-60)+'px';w.style.height=(vh-60)+'px';w.style.left='30px';w.style.top='20px'}
 else if(st==='max'){if(max&&!w.classList.contains('popupMax'))max.click()}
 window.dispatchEvent(new Event('resize'));return 'ok'}"""
CHK = r"""()=>{const f=window.__cw;if(!f)return ['δεν βρέθηκε παράθυρο'];const R=f.getBoundingClientRect(),o=[];
 const vis=e=>{const r=e.getBoundingClientRect();if(r.width<2||r.height<2)return false;const cs=getComputedStyle(e);return cs.visibility!=='hidden'&&cs.display!=='none'&&e.offsetParent!==null};
 const tx=e=>(e.innerText||e.value||e.placeholder||e.getAttribute('aria-label')||e.tagName).trim().replace(/\s+/g,' ').slice(0,28);
 if(R.left<-1||R.top<-1||R.right>innerWidth+1||R.bottom>innerHeight+1)o.push('το παράθυρο βγαίνει από την οθόνη ('+Math.round(R.left)+','+Math.round(R.top)+' '+Math.round(R.width)+'x'+Math.round(R.height)+')');
 const scr=e=>{let p=e.parentElement;while(p&&p!==f.parentElement){const cs=getComputedStyle(p);if(/auto|scroll/.test(cs.overflowX)&&p.scrollWidth>p.clientWidth+2)return p;p=p.parentElement}return null};
 const isTableWrap=e=>!!e.querySelector(':scope>table,:scope>div>table')&&[...e.children].length<=2;
 f.querySelectorAll('*').forEach(e=>{if(!vis(e))return;const cs=getComputedStyle(e);
  if(/auto|scroll/.test(cs.overflowX)&&e.scrollWidth>e.clientWidth+2&&!isTableWrap(e)&&e.tagName!=='TEXTAREA'&&e.tagName!=='SELECT'&&!e.matches('.uTabs,.tabs,.chipRow,.dayStrip,[class*=Strip],[class*=strip]'))o.push('περιεχόμενο φαρδύτερο από το πλαίσιο: '+(e.id||String(e.className).slice(0,30)||e.tagName)+' ('+e.scrollWidth+' > '+e.clientWidth+')');
  if(cs.textOverflow==='ellipsis'&&e.scrollWidth>e.clientWidth+1&&!e.closest('[title]')&&!e.closest('table'))o.push('κομμένο κείμενο χωρίς tooltip: «'+tx(e)+'»')});
 f.querySelectorAll('button,input,select,textarea,h2,h3,h4,label,.uInfo span').forEach(e=>{if(!vis(e))return;const r=e.getBoundingClientRect();
  if((r.right>R.right+1||r.left<R.left-1)&&!scr(e))o.push('έξω από το παράθυρο: «'+tx(e)+'» ('+Math.round(r.left)+'..'+Math.round(r.right)+' / '+Math.round(R.left)+'..'+Math.round(R.right)+')')});
 f.querySelectorAll('table').forEach(t=>{if(!vis(t)||!t.tHead||!t.tBodies[0]||!t.tBodies[0].rows[0])return;const a=t.tHead.rows[0].getBoundingClientRect(),b=t.tBodies[0].rows[0].getBoundingClientRect();
  if(b.width>a.width+3)o.push('κεφαλίδα πίνακα στενότερη από τις γραμμές ('+Math.round(a.width)+' < '+Math.round(b.width)+')')});
 return [...new Set(o)]}"""

T = lambda name, js, tabs=None, wait=2600: {'name': name, 'js': js, 'tabs': tabs or [], 'wait': wait}
MASTER = [('suppliers', 'Προμηθευτής'), ('clients', 'Πελάτης'), ('carriers', 'Μεταφορέας'), ('partners', 'Συνεργάτης'), ('mediaM', 'Μέσο συλλογής'), ('weeeM', 'ΑΗΗΕ'),
          ('materialsM', 'Υλικό'), ('departmentsM', 'Τμήμα'), ('employeesM', 'Εργαζόμενος')]
WINS = []
EXPL={'carriers','mediaM','weeeM','materialsM'}
for tab, label in MASTER:
    WINS.append(T(f'Μητρώα ▸ {label} (νέο)', f"(()=>{{show('master');let t=document.querySelector('.mtab[data-mtab={tab}]');if(t)t.click();setTimeout(()=>{{let p=document.getElementById('{tab}')||document.querySelector('#master .mpanel:not(.hidden)');let b=p&&[...p.querySelectorAll('button')].find(x=>/^\\+/.test(x.textContent.trim())&&x.offsetParent);if(b)b.click()}},700)}})()", wait=3200))
    if tab not in EXPL: WINS.append(T(f'Μητρώα ▸ {label} (προφίλ)', f"(()=>{{show('master');let t=document.querySelector('.mtab[data-mtab={tab}]');if(t)t.click();setTimeout(()=>{{let p=document.querySelector('#master .mpanel:not(.hidden)')||document.getElementById('{tab}');let r=p&&[...p.querySelectorAll('tbody tr[data-id], tbody tr, [data-id]:not(button)')].find(x=>x.offsetParent&&!x.querySelector('.muted')&&!x.closest('thead'));if(r){{let c=[...r.querySelectorAll('td')].find(td=>!td.querySelector('input,button')&&td.textContent.trim());(c||r).click()}}}},1200)}})()", wait=3600))
    WINS.append(T(f'Μητρώα ▸ {label} (ιστορικό αλλαγών)', f"(()=>{{show('master');let t=document.querySelector('.mtab[data-mtab={tab}]');if(t)t.click();setTimeout(()=>{{let p=document.querySelector('#master .mpanel:not(.hidden)');let b=p&&[...p.querySelectorAll('button')].find(x=>/Ιστορικό αλλαγών/.test(x.textContent)&&x.offsetParent);if(b)b.click()}},900)}})()", wait=3400))
ORDER = "(async()=>{let r=await api('/receipts');for(const x of r)for(const l of (x.loads||[]))if(l.order_number==='812143'){b9OpenOrder(x.id,l.id);return}})()"
WINS += [
    T('Νέα Παραλαβή', "show('receipts');prepareNewReceiptPopup()"),
    T('Εντολή ▸ Ταξινόμηση', ORDER, wait=4500),
    T('Εντολή ▸ Παραλαβή', ORDER + ";setTimeout(()=>{let b=[...document.querySelectorAll('#uSoTabs .uTab')].find(x=>x.dataset.ut==='rec');if(b)b.click()},3500)", wait=6000),
    T('Αρχείο διαγραμμένων παραλαβών', "show('receipts');document.getElementById('receiptArchiveBtn').click()", wait=3000),
    T('Αναφορά Παραλαβών', "show('receipts');let b=[...document.querySelectorAll('#receipts button')].find(x=>/Αναφορά/.test(x.textContent)&&x.offsetParent);if(b)b.click()"),
    T('Επιλογή εύρους ημερομηνιών', "show('weee');openDateRangePicker('2026-09-01','2026-09-30',()=>{})"),
    T('Αποθήκη ΑΗΗΕ ▸ κινήσεις γραμμής (κλικ σε γραμμή)', "(async()=>{show('weee');await new Promise(r=>setTimeout(r,2500));document.getElementById('weeePrev').click();await new Promise(r=>setTimeout(r,2500));document.getElementById('weeePrev').click();await new Promise(r=>setTimeout(r,4000));let tr=[...document.querySelectorAll('#weeeProcessRows tr.materialRow')].find(x=>x.cells[3].textContent.trim());if(tr)tr.cells[0].click()})()", wait=12000),
    T('Αποθήκη ΑΗΗΕ ▸ κινήσεις κελιού Παραλαβές', "(async()=>{let tr=[...document.querySelectorAll('#weeeProcessRows tr.materialRow')].find(x=>x.cells[3].textContent.trim());if(tr)tr.cells[3].click()})()", wait=4000),
    T('Αποθήκη ΑΗΗΕ ▸ κινήσεις περιόδου', "(async()=>{show('weee');await new Promise(r=>setTimeout(r,2500));openWeeeMoves('2Α1120','Οθόνες (Τηλεοράσεις) FPD no','receipts','Παραλαβές')})()", wait=5500),
    T('Αποθήκη ΑΗΗΕ ▸ ΜΗ ΑΗΗΕ κινήσεις', "(async()=>{show('weee');await new Promise(r=>setTimeout(r,2500));openWeeeMoves('119999','Άλλα υλικά','all','Κινήσεις')})()", wait=5500),
    T('Αποθήκη ΑΗΗΕ ▸ μέσα συλλογής ▸ ιστορικό μέσου', "(async()=>{show('weee');await new Promise(r=>setTimeout(r,2500));document.getElementById('weeePrev').click();await new Promise(r=>setTimeout(r,2500));document.getElementById('weeePrev').click();await new Promise(r=>setTimeout(r,4000));document.querySelector('[data-weeetab=media]').click();await new Promise(r=>setTimeout(r,2500));let td=document.querySelector('#weeeMediaRows .mediaKg');if(td){td.click();await new Promise(r=>setTimeout(r,2500));let tr=document.querySelector('#floatingEditorBody .mediaRow[data-mid]');if(tr)tr.click()}})()", wait=16000),
    T('Αναφορά Αποθήκης ΑΗΗΕ', "show('weee');document.getElementById('weeeReportBtn').click()"),
    T('Παραγωγή ▸ Διορθώσεις παραγωγής', "show('production');setTimeout(()=>{let r=document.getElementById('prodCorrectionRow');if(r)r.click()},2500)", wait=5000),
    T('Υλικά ▸ Εξαγωγή υλικών', "show('ready');setTimeout(()=>openReadyExportModal(),1500)", wait=4000),
    T('Υλικά ▸ Νέα διόρθωση υλικού', "show('ready');setTimeout(()=>openReadyCorrectionModal(['ΣΙΔΗΡΟΥΧΑ']),1500)", wait=4000),
    T('Μητρώα ▸ Υλικά ▸ Κατηγορίες υλικών', "show('master');document.querySelector('.mtab[data-mtab=materialsM]').click();setTimeout(()=>document.getElementById('materialCatsBtn').click(),800)", wait=3500),
    T('Φορτώσεις ▸ Νέα φόρτωση', "show('loading');setTimeout(()=>nlOpen(),1500)", wait=4000),
    T('Φορτώσεις ▸ φόρτωση', "show('loading');setTimeout(()=>{let tr=document.querySelector('#loadingRows tr[data-id]');if(tr)tr.click()},2500)", wait=5500),
    T('Απογραφή ▸ Αναφορά', "show('inventory');setTimeout(()=>{let b=document.getElementById('invReportBtn');if(b)b.click()},1500)", wait=4000),
    T('Ρυθμίσεις ▸ Προφίλ χρήστη', "(()=>{let m=document.getElementById('settingsMenu');if(m)m.classList.remove('hidden');document.getElementById('profileRow').click()})()",
      tabs=['.profileTabBtn']),
    T('Ρυθμίσεις ▸ Επίπεδα χρηστών', "(()=>{let m=document.getElementById('settingsMenu');if(m)m.classList.remove('hidden');document.getElementById('roleLevelsBtn').click()})()"),
    T('Ρυθμίσεις ▸ Ρυθμίσεις εφαρμογής', "(()=>{let m=document.getElementById('settingsMenu');if(m)m.classList.remove('hidden');document.getElementById('appSettingsBtn').click()})()",
      tabs=['.appSettingsItem']),
    T('Αντίγραφα ασφαλείας', "(()=>{let b=document.getElementById('backupAlert');if(b){b.classList.remove('hidden');b.click()}})()"),
]
WINS += [
    T('Μητρώα ▸ Μεταφορέας (προφίλ)', "(async()=>{show('master');let o=await api('/master/organizations?role=CARRIER&include_inactive=true');editOrgPopup('CARRIER','carrier',o[0])})()", wait=3500),
    T('Μητρώα ▸ Μέσο συλλογής (προφίλ)', "(async()=>{show('master');let m=await api('/master/media?include_inactive=true');editMediumPopup(m[0])})()", wait=3500),
    T('Μητρώα ▸ ΑΗΗΕ (προφίλ)', "(async()=>{show('master');let c=await api('/master/weee-display?include_inactive=true');editWeeePopup(c[0])})()", wait=3500),
    T('Μητρώα ▸ Υλικό (προφίλ)', "(async()=>{show('master');let m=await api('/master/materials?include_inactive=true');editMaterialPopup(m[0])})()", wait=3500),
]
CLOSE ="(()=>{document.querySelectorAll('#floatingEditor,#receiptForm,#sortingDetail,#stockModal,#reportPopup').forEach(e=>{e.classList.add('hidden');e.classList.remove('popupMax');e.style.width='';e.style.height=''});document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));document.querySelectorAll('.drpPop,.repPop,.autoCloseMenu').forEach(e=>e.remove());window.__cw=null;let m=document.getElementById('settingsMenu');if(m)m.classList.add('hidden')})()"


def main():
    os.makedirs(OUT, exist_ok=True)
    found, opened, missing = {}, [], []
    with sync_playwright() as p:
        b = launch(p)
        try:
            for z in ZOOMS:
                pg = b.new_page(viewport={'width': int(VIEW[0] / z), 'height': int(VIEW[1] / z)}, device_scale_factor=z)
                pg.on('pageerror', lambda e: print('pageerror', str(e)[:160]))
                pg.goto(BASE + '/', wait_until='networkidle', timeout=90000); pg.wait_for_selector('#loginBtn', state='visible', timeout=60000)
                pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=90000); pg.wait_for_timeout(1500)
                vw, vh = pg.evaluate('[innerWidth,innerHeight]')
                for w in WINS:
                    pg.evaluate(CLOSE); pg.wait_for_timeout(250)
                    try: pg.evaluate(w['js'])
                    except Exception as e: missing.append((w['name'], str(e)[:80])); continue
                    pg.wait_for_timeout(w['wait'])
                    if not pg.evaluate(FIND, WINSEL):
                        if z == ZOOMS[0]: missing.append((w['name'], 'δεν άνοιξε'))
                        continue
                    if z == ZOOMS[0]: opened.append(w['name'])
                    tabsel = w['tabs'][0] if w['tabs'] else None
                    ntabs = pg.evaluate(f"document.querySelectorAll('[data-cw] {tabsel}').length") if tabsel else 1
                    for ti in range(max(1, ntabs)):
                        if tabsel:
                            pg.evaluate(f"(()=>{{let b=document.querySelectorAll('[data-cw] {tabsel}')[{ti}];if(b)b.click()}})()"); pg.wait_for_timeout(900)
                        popover = pg.evaluate("!!(window.__cw&&window.__cw.matches('.repPop,.drpPop'))")
                        for st in (('normal',) if popover else ('normal', 'small', 'large', 'max')):
                            pg.evaluate(STATE, [st, vw, vh]); pg.wait_for_timeout(700)
                            tag = f'ζουμ {int(z * 100)}% · {st}'
                            nm = w['name'] + (f' · καρτέλα {ti + 1}' if tabsel else '')
                            pg.screenshot(path=os.path.join(OUT, re.sub(r'[^\w.-]', '_', f'{nm}_{int(z * 100)}_{st}')[:150] + '.png'))
                            for m in pg.evaluate(CHK) + (pg.evaluate("(()=>{document.querySelectorAll('[data-cw]').forEach(x=>{if(x!==window.__cw)x.removeAttribute('data-cw')});return 1})()") and pg.evaluate(LINES_JS, '[data-cw]')):
                                found.setdefault((nm, m), []).append(tag)
                pg.close()
        finally:
            b.close()
    print(f'ΠΑΡΑΘΥΡΑ ΠΟΥ ΕΛΕΓΧΘΗΚΑΝ ({len(opened)}):')
    for n in opened: print('  ·', n)
    if missing:
        print('ΔΕΝ ΑΝΟΙΞΑΝ:')
        for n, why in missing: print('  ·', n, '—', why)
    for (n, m), tags in found.items():
        print(f'[{n}] {m}  — σε: {", ".join(tags[:3])}{" +" + str(len(tags) - 3) if len(tags) > 3 else ""}')
    print(f'{len(found)} προβλήματα' if found else '0 προβλήματα', '· screenshots:', OUT)


if __name__ == '__main__':
    main()
