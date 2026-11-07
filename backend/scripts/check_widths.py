"""Έλεγχος πλάτους και άκρων πινάκων και καρτών (μέρος του check_tables.py).
Για κάθε ορατό πίνακα: (1) ο πίνακας πιάνει όλο το πλάτος του πλαισίου του (εκτός αν ο ίδιος κάνει οριζόντιο scroll),
(2) το πλαίσιο του πίνακα έχει ΙΔΙΟ περιθώριο αριστερά και δεξιά μέσα στη γονική κάρτα/παράθυρο, (3) δεν είναι κολλημένο ή κομμένο στην άκρη.
Για κάθε ορατή κάρτα: ίδιο περιθώριο αριστερά/δεξιά μέσα στον γονέα της, τίποτα κομμένο ή κολλημένο.
Τρέχει στις σελίδες/καρτέλες και στα παράθυρα (Ταξινόμηση, Νέα Παραλαβή, φόρμες) σε 1366 και 1920 πλάτος.
Τυπώνει μόνο προβλήματα. Μόνο ανάγνωση."""
import sys
from playwright.sync_api import sync_playwright
from _browser import launch
import check_fields

CHECK = """(sel)=>{
 const root=[...document.querySelectorAll(sel)].find(e=>!e.classList.contains('hidden')&&e.getBoundingClientRect().height>20);if(!root)return ['(δεν βρέθηκε '+sel+')'];
 const bad=[],R=e=>e.getBoundingClientRect(),vis=e=>{if(!e.offsetParent)return false;const q=R(e);return q.width>30&&q.height>10};
 const nm=e=>(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/ +/).slice(0,2).join('.'):'')||e.tagName;
 const sib=e=>{const p=e.parentElement;if(!p)return false;const d=getComputedStyle(p).display;if(!/grid|flex/.test(d))return false;const q=R(e);return [...p.children].some(o=>o!==e&&vis(o)&&Math.abs(R(o).top-q.top)<q.height*0.6)};
 const WRAP='.prodTableWrap,.tablewrap,.sfWrap,.registryTableWrap,.sortingCatWrap';
 root.querySelectorAll('table').forEach(t=>{
  if(!vis(t)||t.closest('.hidden,[hidden]'))return;
  let w=t.closest(WRAP);if(!w){w=t.parentElement}
  if(!vis(w))return;
  if(t.dataset.cwGap==='1')bad.push('πίνακας '+nm(t)+': μένει κενό δεξιά (δεν μοιράστηκε όλο το πλάτος στις στήλες)');
  const wr=R(w),tr=R(t),sc=w.scrollWidth>w.clientWidth+2&&/auto|scroll/.test(getComputedStyle(w).overflowX);
  const hostSc=(()=>{const h=t.closest('#weeeBody,#weee');return !!h&&/auto|scroll/.test(getComputedStyle(h).overflowX)})();      // Αποθήκη ΑΗΗΕ: το οριζόντιο scroll το κάνει όλο το παράθυρο της σελίδας (όχι ο κάθε πίνακας)
  if(!sc&&!hostSc&&t.offsetWidth>w.clientWidth+3&&!/auto|scroll/.test(getComputedStyle(w).overflowX))bad.push('πίνακας '+nm(t)+': βγαίνει έξω από το πλαίσιό του κομμένος δεξιά (πίνακας '+Math.round(t.offsetWidth)+'px, πλαίσιο '+Math.round(w.clientWidth)+'px)');
  if(!sc&&w.clientWidth-t.offsetWidth>3)bad.push('πίνακας '+nm(t)+' στο '+nm(w)+': δεν πιάνει όλο το πλάτος (πίνακας '+Math.round(t.offsetWidth)+'px, πλαίσιο '+Math.round(w.clientWidth)+'px)');
  const rail=[...(w.parentElement?w.parentElement.children:[])].some(o=>o!==w&&o.offsetParent&&R(o).width>0&&R(o).width<=20&&Math.abs(R(o).top-wr.top)<5);   // στενή λωρίδα ενδείξεων (π.χ. αρνητικά) δίπλα στον πίνακα
  const p=w.parentElement;if(!p||p===root.parentElement||sib(w)||rail)return;
  const pr=R(p),cs=getComputedStyle(p),L=wr.left-pr.left-parseFloat(cs.paddingLeft||0)-parseFloat(cs.borderLeftWidth||0),Rr=pr.right-wr.right-parseFloat(cs.paddingRight||0)-parseFloat(cs.borderRightWidth||0);
  if(Math.abs(L-Rr)>3&&!sc)bad.push('πίνακας '+nm(t)+': ανόμοια περιθώρια αριστερά/δεξιά ('+Math.round(L)+'px / '+Math.round(Rr)+'px) μέσα στο '+nm(p));
  if(wr.right>pr.right+1||wr.left<pr.left-1)bad.push('πίνακας '+nm(t)+': βγαίνει έξω από το '+nm(p));
 });
 root.querySelectorAll('.card').forEach(c=>{
  if(!vis(c)||c.closest('.hidden'))return;
  const p=c.parentElement;if(!p||sib(c))return;const pr=R(p),cr=R(c),cs=getComputedStyle(p);
  if(c.scrollWidth>c.clientWidth+2&&getComputedStyle(c).overflowX==='visible'&&c.scrollWidth>cr.width+2)bad.push('κάρτα '+nm(c)+': περιεχόμενο κομμένο δεξιά');
  const L=cr.left-pr.left-parseFloat(cs.paddingLeft||0)-parseFloat(cs.borderLeftWidth||0),Rr=pr.right-cr.right-parseFloat(cs.paddingRight||0)-parseFloat(cs.borderRightWidth||0);
  if(Math.abs(L-Rr)>3&&Math.abs(L)+Math.abs(Rr)>0&&cr.width<pr.width-6)bad.push('κάρτα '+nm(c)+': ανόμοια περιθώρια αριστερά/δεξιά ('+Math.round(L)+'px / '+Math.round(Rr)+'px) μέσα στο '+nm(p));
  if(cr.right>pr.right+1||cr.left<pr.left-1)bad.push('κάρτα '+nm(c)+': βγαίνει έξω από το '+nm(p));
 });
 return [...new Set(bad)];
}"""


def run(B, widths=((1366, 800), (1920, 1000))):
    problems = []
    with sync_playwright() as p:
        b = launch(p)
        try:
            for W, H in widths:
                pg = b.new_page(viewport={'width': W, 'height': H})
                pg.goto(B + '/', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                tag = f'{W}px'
                # 1) κάθε σελίδα και καρτέλα
                for v in pg.evaluate("[...document.querySelectorAll('.nav button')].map(b=>b.dataset.view)"):
                    pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(900)
                    sel = f"#{v} .tab,#{v} .mtab,#{v} .productionTab,#{v} .weeeTabBtn,#{v} .readyGroupTab,#{v} .receiptMode,#{v} .profileTabBtn"
                    n = max(pg.evaluate(f"[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent).length"), 1)
                    for i in range(n):
                        pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()"); pg.wait_for_timeout(700)
                        for m in pg.evaluate(CHECK, f'#{v}'):
                            if not m.startswith('('): problems.append(f'[{tag} σελίδα {v} / καρτέλα {i}] {m}')
                # 2) παράθυρα: Ταξινόμηση (κανονικό και μεγιστοποιημένο), φόρμες και ό,τι ανοίγει το check_fields
                sd = pg.evaluate("(async()=>{try{show('receipts');let r=await api('/receipts');let l=(r.find(x=>x.loads&&x.loads.length)||{loads:[]}).loads[0];return l?l.id:null}catch(e){return null}})()")
                steps = []
                if sd:
                    steps.append(('Ταξινόμηση', f"show('receipts');openSortingDetail('{sd}')", '#sortingDetail', True))
                steps.append(('Ταξινόμηση (στενό αποθηκευμένο μέγεθος)', f"localStorage.setItem('popupSizes1',JSON.stringify({{'win:sorting':{{w:700,h:700}}}}));show('receipts');openSortingDetail('{sd}')", '#sortingDetail', False)) if sd else None
                for name, js, sel in check_fields.STEPS:
                    steps.append((name, js, sel, False))
                for name, js, sel, mx in steps:
                    try:
                        pg.evaluate(js); pg.wait_for_timeout(1500)
                        for m in pg.evaluate(CHECK, sel):
                            if not m.startswith('('): problems.append(f'[{tag} {name}] {m}')
                        if mx:
                            pg.evaluate("document.querySelector('#sortingDetail [data-win=max]').click()"); pg.wait_for_timeout(700)
                            for m in pg.evaluate(CHECK, sel):
                                if not m.startswith('('): problems.append(f'[{tag} {name} μεγιστοποιημένο] {m}')
                    except Exception:
                        pass
                    pg.evaluate("document.querySelectorAll('#floatingEditor,#receiptForm,#sortingDetail,.floatPanel').forEach(e=>{e.classList.add('hidden');e.classList.remove('popupMax','popupMin')})")
                pg.evaluate("localStorage.removeItem('popupSizes1')")
                pg.close()
        finally:
            b.close()
    seen = set(); out = []
    for m in problems:
        if m not in seen: seen.add(m); out.append(m)
    for m in out: print(m)
    return len(out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('ΠΡΟΒΛΗΜΑΤΑ ΠΛΑΤΟΥΣ/ΑΚΡΩΝ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
