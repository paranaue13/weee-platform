"""Έλεγχος στοίχισης πεδίων (ΚΑΝΟΝΑΣ εφαρμογής: πεδία της ΙΔΙΑΣ γραμμής ξεκινούν και τελειώνουν στο ίδιο ύψος).
Μετρά ΠΡΑΓΜΑΤΙΚΑ (browser): σε κάθε προφίλ/φόρμα/παράθυρο, σε κάθε σελίδα και καρτέλα, τα πεδία που βρίσκονται στην ίδια γραμμή (grid/flex) πρέπει να έχουν ίδιο πάνω και κάτω όριο (ανοχή 1,5px).
Τυπώνει ΜΟΝΟ προβλήματα. Χρήση: python backend/scripts/check_fields.py [http://127.0.0.1:8000]  (μόνο ανάγνωση: ανοίγει φόρμες χωρίς να αποθηκεύει)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from _browser import launch

CHECK = r"""(sel)=>{
 // Κανόνας: πεδία της ΙΔΙΑΣ γραμμής ξεκινούν και τελειώνουν στο ίδιο ύψος. Κάθε «πεδίο» = στοιχείο με ΕΝΑ χειριστήριο (input/select/textarea/κουμπί επιλογής)
 const root=[...document.querySelectorAll(sel)].find(e=>!e.classList.contains('hidden')&&e.getBoundingClientRect().height>20);if(!root)return ['(δεν βρέθηκε '+sel+')'];
 const CTL='input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]):not([type=range]),select,textarea,button.sgSel,.tfIn';
 const vis=e=>e.offsetParent&&e.getBoundingClientRect().height>2&&e.getBoundingClientRect().width>2;
 const bad=[];const R=e=>e.getBoundingClientRect();
 const cap=e=>((e.closest('label')||e.parentElement).textContent||'').trim().replace(/\s+/g,' ').replace(/\?/g,'').slice(0,24);
 root.querySelectorAll('*').forEach(par=>{
  const kids=[...par.children].filter(vis);if(kids.length<2)return;
  const st=getComputedStyle(par);if(!/flex|grid/.test(st.display))return;
  const fields=[];
  kids.forEach(k=>{
   let ctls=k.matches(CTL)?[k]:[...k.querySelectorAll(CTL)].filter(vis);
   if(ctls.length===1)fields.push({k,c:ctls[0]});
  });
  if(fields.length<2)return;
  // ομαδοποίηση ανά γραμμή (το κουτί του πεδίου ξεκινά στο ίδιο ύψος)
  const rows=[];fields.forEach(f=>{const t=R(f.k).top;let r=rows.find(x=>Math.abs(x.t-t)<=3);if(!r){r={t,f:[]};rows.push(r)}r.f.push(f)});
  rows.forEach(r=>{if(r.f.length<2)return;
   const tops=r.f.map(f=>R(f.c).top),bots=r.f.map(f=>R(f.c).bottom);
   const dt=Math.max(...tops)-Math.min(...tops),db=Math.max(...bots)-Math.min(...bots);
   if(dt>1.5||db>1.5)bad.push('«'+r.f.map(f=>cap(f.c)).join('» | «')+'»: διαφορά πάνω '+dt.toFixed(1)+'px, κάτω '+db.toFixed(1)+'px');
  });
 });
 return [...new Set(bad)];
}
"""
OPENERS = [
 ('Προφίλ υλικού (νέο)', "editMaterialPopup()"),
 ('Προφίλ υλικού 00001', "editMaterialPopup(materialsCache.find(m=>m.galaxy_code==='00001'))"),
 ('Προφίλ υλικού εμπορικό', "editMaterialPopup(materialsCache.find(m=>m.is_commercial))"),
 ('Εργαζόμενος (νέος)', "editEmployeePopup()"),
 ('Εργαζόμενος', "editEmployeePopup((employeesCache||[])[0])"),
 ('ΑΗΗΕ (νέο)', "editWeeePopup()"),
 ('Τμήμα (νέο)', "editDepartmentPopup()"),
 ('Μέσο συλλογής (νέο)', "editMediumPopup()"),
 ('Εξοπλισμός (νέος)', "editEquipmentPopup()"),
 ('Αναλώσιμο (νέο)', "editConsumablePopup()"),
 ('Οργανισμός (νέος)', "editOrgPopup('supplier')"),
 ('Container (νέο)', "editContainerPopup()"),
]
STEPS = [
 ('Νέος προμηθευτής', "show('master');document.querySelector('.mtab[data-mtab=suppliers]').click();setTimeout(()=>document.getElementById('supplierCreate').click(),300)", '#floatingEditor'),
 ('Νέος πελάτης', "show('master');document.querySelector('.mtab[data-mtab=clients]').click();setTimeout(()=>document.getElementById('clientCreate').click(),300)", '#floatingEditor'),
 ('Νέος μεταφορέας', "show('master');document.querySelector('.mtab[data-mtab=carriers]').click();setTimeout(()=>document.getElementById('carrierCreate').click(),300)", '#floatingEditor'),
 ('Νέος συνεργάτης', "show('master');document.querySelector('.mtab[data-mtab=partners]').click();setTimeout(()=>document.getElementById('partnerCreate').click(),300)", '#floatingEditor'),
 ('Νέο υλικό (κουμπί)', "show('master');document.querySelector('.mtab[data-mtab=materialsM]').click();setTimeout(()=>document.getElementById('materialCreate').click(),300)", '#floatingEditor'),
 ('Νέο ΑΗΗΕ (κουμπί)', "show('master');document.querySelector('.mtab[data-mtab=weeeNamesM]').click();setTimeout(()=>document.getElementById('weeeCreate').click(),300)", '#floatingEditor'),
 ('Νέο τμήμα (κουμπί)', "show('master');document.querySelector('.mtab[data-mtab=departmentsM]').click();setTimeout(()=>document.getElementById('departmentCreate').click(),300)", '#floatingEditor'),
 ('Νέος εργαζόμενος (κουμπί)', "show('master');document.querySelector('.mtab[data-mtab=employeesM]').click();setTimeout(()=>document.getElementById('employeeCreate').click(),300)", '#floatingEditor'),
 ('Νέο μέσο (κουμπί)', "show('master');document.querySelector('.mtab[data-mtab=mediaM]').click();setTimeout(()=>document.getElementById('mediumCreate').click(),300)", '#floatingEditor'),
 ('Ρυθμίσεις εφαρμογής', "document.getElementById('appSettingsBtn').click()", '#floatingEditor'),
 ('Επίπεδα χρηστών', "document.getElementById('roleLevelsBtn').click()", '#floatingEditor'),
 ('Νέα παραλαβή', "show('receipts');prepareNewReceiptPopup()", '#receiptForm'),
 ('Νέα φόρτωση', "show('loading');(typeof openNewLoadingPopup==='function')&&openNewLoadingPopup()", '#floatingEditor'),
 ('Εξαγωγή υλικών (Υλικά)', "show('ready');(typeof openReadyExportModal==='function')&&openReadyExportModal()", '.floatPanel:not(.hidden),#floatingEditor'),
 ('Υπάρχουσα παραλαβή', "show('receipts');setTimeout(()=>openReceiptPopup((receiptRowsAll||[])[0].id),800)", '#receiptForm'),
 ('Μαζική επεξεργασία υλικών', "show('master');document.querySelector('.mtab[data-mtab=materialsM]').click();setTimeout(()=>{(typeof openMaterialBulkEdit==='function')&&openMaterialBulkEdit([materialsCache[0].id,materialsCache[1].id])},500)", '#floatingEditor'),
 ('Διόρθωση υλικών (Υλικά)', "show('ready');(typeof openReadyCorrectionModal==='function')&&openReadyCorrectionModal()", '.floatPanel:not(.hidden),#floatingEditor'),
]

def run(B):
    problems = []
    with sync_playwright() as p:
        b = launch(p)
        try:
            pg = b.new_page(viewport={'width': 1366, 'height': 800})
            pg.goto(B + '/', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
            # 1) προφίλ (Μητρώα)
            pg.click('.nav button[data-view="master"]'); pg.wait_for_timeout(800)
            for t in ('materialsM', 'employeesM'):
                pg.evaluate("(t)=>document.querySelectorAll('.mtab').forEach(b=>{if(b.dataset.mtab===t)b.click()})", t); pg.wait_for_timeout(1200)
            for name, js in OPENERS:
                try:
                    pg.evaluate(js); pg.wait_for_timeout(500)
                    for m in pg.evaluate(CHECK, '#floatingEditor'):
                        if not m.startswith('('): problems.append(f'[{name}] {m}')
                except Exception:
                    pass
                pg.evaluate("document.getElementById('floatingEditor').classList.add('hidden')")
            # 2) άλλα παράθυρα και φόρμες
            for name, js, sel in STEPS:
                try:
                    pg.evaluate(js); pg.wait_for_timeout(1300)
                    for m in pg.evaluate(CHECK, sel):
                        if not m.startswith('('): problems.append(f'[{name}] {m}')
                except Exception:
                    pass
                pg.evaluate("document.querySelectorAll('#floatingEditor,#receiptForm,.floatPanel').forEach(e=>e.classList.add('hidden'))")
            # 3) κάθε σελίδα και καρτέλα
            for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
                pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1000)
                sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn"
                n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
                for i in range(n):
                    pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()"); pg.wait_for_timeout(700)
                    for m in pg.evaluate(CHECK, f'#{v}'):
                        if not m.startswith('('): problems.append(f'[σελίδα {v} / καρτέλα {i}] {m}')
        finally:
            b.close()
    for m in problems: print(m)
    return len(problems)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('ΠΡΟΒΛΗΜΑΤΑ ΣΤΟΙΧΙΣΗΣ ΠΕΔΙΩΝ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
