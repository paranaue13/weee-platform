"""Οπτικός έλεγχος με πραγματικά screenshots (Windows): κάθε σελίδα, κάθε καρτέλα, βασικά παράθυρα,
σε μέγεθος μικρό / μεσαίο / φαρδύ και ζουμ οθόνης 100 / 125 / 150 %.
Ελέγχει ΞΕΧΩΡΙΣΤΑ: (Γ) γραμμές/περιγράμματα που σταματούν πριν την άκρη ή πριν από στοιχεία της ίδιας σειράς,
(Ο) όρια: στοιχεία κομμένα/εκτός οθόνης, (Ε) επικαλύψεις, (Π) παράθυρα που δεν γεμίζουν το πλάτος τους,
και ό,τι βρίσκει το SCAN_JS του check_split. Αποθηκεύει τα screenshots στον φάκελο OUT (2ο όρισμα).
Χρήση (ΜΟΝΟ σε server με αντίγραφο δεδομένων): python check_visual.py http://127.0.0.1:8024 <φάκελος> [γρήγορο]"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
from check_split import SCAN_JS, GEN

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000').rstrip('/')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get('TEMP', '.'), 'check_visual')
QUICK = len(sys.argv) > 3

LINES_JS = r"""(scope)=>{const out=[];
 const vis=e=>{const r=e.getBoundingClientRect();if(r.width<2||r.height<2)return false;const cs=getComputedStyle(e);return cs.visibility!=='hidden'&&cs.display!=='none'&&e.offsetParent!==null};
 const tx=e=>(e.innerText||e.value||e.getAttribute('aria-label')||e.title||e.id||e.className||'').toString().trim().replace(/\s+/g,' ').slice(0,26);
 const root=document.querySelector(scope)||document.body;
 const TABS='.tab,.mtab,.productionTab,.weeeTabBtn,.readyGroupTab,.receiptMode,.profileTabBtn,.uTab,[role=tab]';
 // (Γ) γραμμή κάτω από καρτέλες: το στοιχείο με το κάτω περίγραμμα που περιέχει καρτέλες πρέπει να φτάνει ως το δεξί άκρο του περιεχομένου
 //     και να περνά κάτω από ΟΛΑ τα στοιχεία της ίδιας σειράς
 const lineOf=e=>{const cs=getComputedStyle(e);const bw=parseFloat(cs.borderBottomWidth)||0;return bw>=0.5&&cs.borderBottomStyle!=='none'&&!/rgba\(0, 0, 0, 0\)|transparent/.test(cs.borderBottomColor)};
 const rows=new Set();root.querySelectorAll(TABS).forEach(t=>{if(!vis(t)||t.closest('table'))return;let p=t.parentElement,d=0;while(p&&p!==root&&d<4){if(lineOf(p)&&p.getBoundingClientRect().width>120){rows.add(p);break}p=p.parentElement;d++}});
 rows.forEach(r=>{const R=r.getBoundingClientRect();
  // όριο περιεχομένου: η πλησιέστερη .view / παράθυρο
  const box=r.closest('.view,.floatPanel,#floatingEditor,.uWin,#receiptForm,#sortingDetail')||root;const B=box.getBoundingClientRect(),cs=getComputedStyle(box);
  const right=B.right-(parseFloat(cs.paddingRight)||0)-(parseFloat(cs.borderRightWidth)||0)-(box.clientWidth&&box.scrollHeight>box.clientHeight?box.offsetWidth-box.clientWidth-(parseFloat(cs.borderLeftWidth)||0)-(parseFloat(cs.borderRightWidth)||0):0);
  const left=B.left+(parseFloat(cs.paddingLeft)||0)+(parseFloat(cs.borderLeftWidth)||0);
  if(R.right<right-6)out.push('Γ: γραμμή καρτελών «'+tx(r.querySelector(TABS))+'…» σταματά '+Math.round(right-R.right)+'px πριν από το δεξί άκρο');
  if(R.left>left+6)out.push('Γ: γραμμή καρτελών «'+tx(r.querySelector(TABS))+'…» ξεκινά '+Math.round(R.left-left)+'px μετά το αριστερό άκρο');
  // στοιχεία της ίδιας σειράς (αδέλφια του πατέρα) δεξιά από το τέλος της γραμμής
  const par=r.parentElement;if(par)[...par.children].forEach(s=>{if(s===r||!vis(s))return;const S=s.getBoundingClientRect();
   if(S.bottom>R.top+4&&S.top<R.bottom-4&&S.left>=R.right-2&&!(lineOf(par)&&par.getBoundingClientRect().bottom<=R.bottom+14))out.push('Γ: η γραμμή καρτελών «'+tx(r.querySelector(TABS))+'…» δεν περνά κάτω από «'+tx(s)+'»')});
 });
 // (Π) παράθυρα: πλαίσια (fieldset/ενότητες) που αφήνουν κενό δεξιά μέσα σε φαρδύ παράθυρο
 document.querySelectorAll('#floatingEditor:not(.hidden) .floatPanelBody, .floatPanel:not(.hidden) .floatPanelBody').forEach(body=>{if(!vis(body))return;const B=body.getBoundingClientRect(),cs=getComputedStyle(body),inR=B.right-(parseFloat(cs.paddingRight)||0)-(body.offsetWidth-body.clientWidth);
  [...body.querySelectorAll('fieldset,.pfSec,.pfBox,.formSection,section,.card')].filter(vis).forEach(f=>{const F=f.getBoundingClientRect();if(f.parentElement&&f.parentElement.closest('fieldset,.pfSec,.pfBox,.formSection,section,.card'))return;
   if(F.right<inR-24&&B.width>700)out.push('Π: πλαίσιο «'+tx(f.querySelector('legend,h3,h4,b')||f)+'» αφήνει '+Math.round(inR-F.right)+'px κενό δεξιά στο παράθυρο')})});
 return [...new Set(out)]}"""

SIZES = [('μικρό', 1280, 720), ('μεσαίο', 1440, 900), ('φαρδύ', 1920, 1080)]
ZOOMS = [1, 1.25, 1.5]
if QUICK:
    SIZES = [SIZES[0], SIZES[2]]; ZOOMS = [1, 1.5]

CLOSE = "document.querySelectorAll('#floatingEditor,#receiptForm,#sortingDetail').forEach(e=>e.classList.add('hidden'));document.querySelectorAll('.floatPanel').forEach(e=>{if(e.id!=='floatingEditor')e.remove()})"
POPUPS = [
    ('Μητρώα ▸ Νέο υλικό', "show('master');document.querySelector('.mtab[data-mtab=materialsM]').click();setTimeout(()=>document.getElementById('materialCreate').click(),400)", '#floatingEditor'),
    ('Προφίλ Υλικού', "(async()=>{show('master');let m=await api('/master/materials?include_inactive=true');editMaterialPopup(m[0])})()", '#floatingEditor'),
    ('Προφίλ Υλικού (μεγιστοποιημένο)', "(async()=>{show('master');let m=await api('/master/materials?include_inactive=true');editMaterialPopup(m[0]);setTimeout(()=>{let b=[...document.querySelectorAll('#floatingEditor .winCtl')][1];if(b)b.click()},500)})()", '#floatingEditor'),
    ('Μητρώα ▸ Τμήμα', "show('master');editDepartmentPopup()", '#floatingEditor'),
    ('Μητρώα ▸ Εργαζόμενος', "show('master');editEmployeePopup()", '#floatingEditor'),
    ('Νέα Παραλαβή', "show('receipts');prepareNewReceiptPopup()", '#receiptForm'),
    ('Ταξινόμηση', "(async()=>{show('receipts');let r=await api('/receipts');let l=(r.find(x=>x.loads&&x.loads.length)||{loads:[]}).loads[0];if(l)openSortingDetail(l.id)})()", '#sortingDetail'),
    ('Ρυθμίσεις ▸ Προφίλ', "(()=>{let m=document.getElementById('settingsMenu');if(m)m.classList.remove('hidden');let r=document.getElementById('profileRow');if(r)r.click()})()", 'body'),
    ('Ρυθμίσεις ▸ Εφαρμογή', "(()=>{let m=document.getElementById('settingsMenu');if(m)m.classList.remove('hidden');let r=document.getElementById('appSettingsBtn');if(r)r.click()})()", 'body'),
    ('Παρουσιολόγιο', "document.getElementById('openPresence').click()", '#presence'),
]


def views(pg):
    return pg.evaluate("[...document.querySelectorAll('.nav button[data-view]')].map(b=>b.dataset.view)")


def tabs(pg, v):
    return pg.evaluate("""([v,sel])=>{const s=document.getElementById(v);if(!s)return 0;return [...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table')).length}""", [v, GEN])


def click_tab(pg, v, i):
    pg.evaluate("""([v,sel,i])=>{const s=document.getElementById(v);const l=[...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table'));if(l[i])l[i].click()}""", [v, GEN, i])


def main():
    os.makedirs(OUT, exist_ok=True)
    total = 0
    seen = {}
    with sync_playwright() as p:
        b = launch(p)
        try:
            for sname, W, H in SIZES:
                for z in ZOOMS:
                    pg = b.new_page(viewport={'width': int(W / z), 'height': int(H / z)}, device_scale_factor=z)
                    pg.on('pageerror', lambda e: print('pageerror', str(e)[:160]))
                    pg.goto(BASE + '/', wait_until='networkidle', timeout=90000); pg.wait_for_selector('#loginBtn', state='visible', timeout=60000)
                    pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=90000); pg.wait_for_timeout(1500)
                    tag = f'{sname} {W}x{H} · ζουμ {int(z * 100)}%'
                    for v in views(pg):
                        pg.click(f'.nav button[data-view="{v}"]'); pg.wait_for_timeout(2500)
                        n = max(1, tabs(pg, v))
                        for i in range(n):
                            if n > 1: click_tab(pg, v, i); pg.wait_for_timeout(1800)
                            name = f'{v}{"/" + str(i) if n > 1 else ""}'
                            pg.screenshot(path=os.path.join(OUT, re.sub(r'[^\w.-]', '_', f'{sname}_{int(z * 100)}_{name}') + '.png'))
                            msgs = pg.evaluate(LINES_JS, f'#{v}') + pg.evaluate(SCAN_JS)
                            for m in msgs:
                                k = (name, m)
                                seen.setdefault(k, []).append(tag)
                    for name, js, sel in POPUPS:
                        pg.evaluate(CLOSE); pg.wait_for_timeout(200); pg.evaluate(js); pg.wait_for_timeout(2200)
                        pg.screenshot(path=os.path.join(OUT, re.sub(r'[^\w.-]', '_', f'{sname}_{int(z * 100)}_win_{name}') + '.png'))
                        for m in pg.evaluate(LINES_JS, sel) + (pg.evaluate(SCAN_JS) if sel == '#presence' else []):
                            seen.setdefault(('παράθυρο ' + name, m), []).append(tag)
                        pg.evaluate(CLOSE)
                    pg.close()
        finally:
            b.close()
    for (name, m), tags in seen.items():
        total += 1
        print(f'[{name}] {m}  — σε: {", ".join(tags[:3])}{" +" + str(len(tags) - 3) if len(tags) > 3 else ""}')
    print(f'{total} προβλήματα' if total else '0 προβλήματα', '· screenshots:', OUT)


if __name__ == '__main__':
    main()
