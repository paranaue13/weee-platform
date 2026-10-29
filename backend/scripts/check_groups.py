"""Έλεγχος πινάκων Υλικών με ΑΝΟΙΧΤΕΣ ομάδες στηλών (ΠΛΑΣΤΙΚΑ ΜΕΡΗ, 00195, TONER, ΛΑΜΠΤΗΡΕΣ, Συσκευές…): μετράει πραγματικές θέσεις/ύψη.
 Για κάθε καρτέλα Υλικών, με όλες τις ομάδες ανοιχτές, σε ποσοστά μεγέθους 85% / 100% / 125%:
  1. κάθε γραμμή (σώμα, Διορθώσεις, Σύνολο, Αποστολές, Τρέχον απόθεμα…): όλα τα κελιά (μέσα και έξω από ομάδα) ίδιο πάνω/κάτω όριο
  2. κεφαλίδα: η γειτονική στήλη (rowspan) έχει το ίδιο ύψος με τίτλο ομάδας + υποστήλες
  3. κανένα κελί (κεφαλίδα ή σώμα) με κομμένο/ξεχειλισμένο κείμενο
  4. ίδιο πάχος/χρώμα οριζόντιων περιγραμμάτων μέσα και έξω από την ομάδα
 Τυπώνει ΜΟΝΟ προβλήματα. Χρήση: python backend/scripts/check_groups.py [http://127.0.0.1:8000]  (μόνο ανάγνωση)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from _browser import launch

JS = """(()=>{const t=document.querySelector('#readyMatHead').closest('table'),bad=[];
 t.querySelectorAll('tr').forEach(tr=>{const cs=[...tr.children].filter(c=>c.offsetParent&&c.rowSpan<=1&&!c.classList.contains('stkTotal'));if(cs.length<2)return;
  const tops=cs.map(c=>c.getBoundingClientRect().top),bots=cs.map(c=>c.getBoundingClientRect().bottom);
  const dt=Math.max(...tops)-Math.min(...tops),db=Math.max(...bots)-Math.min(...bots);
  if(dt>0.6||db>0.6)bad.push('γραμμή «'+(tr.children[0].textContent||'').trim().slice(0,18)+'»: διαφορά πάνω '+dt.toFixed(1)+' / κάτω '+db.toFixed(1)+'px');
  const g=cs.find(c=>c.classList.contains('rmG')&&!c.classList.contains('rmGL')&&!c.classList.contains('rmGR')),n=cs.find(c=>!c.classList.contains('rmG')&&!c.classList.contains('rmGL')&&c.offsetParent&&c!==cs[0]);
  if(g&&n&&tr.parentElement.tagName!=='THEAD'){const a=getComputedStyle(g),b=getComputedStyle(n);if(a.borderBottomWidth!==b.borderBottomWidth||a.borderBottomColor!==b.borderBottomColor)bad.push('γραμμή «'+(tr.children[0].textContent||'').trim().slice(0,18)+'»: διαφορετικό περίγραμμα μέσα στην ομάδα')}});
 const hr=[...document.querySelectorAll('#readyMatHead tr')];
 if(hr.length>1){const h1=[...hr[0].children].filter(c=>c.offsetParent),nb=h1.find(c=>c.rowSpan>1&&c.dataset.material),gt=h1.find(c=>c.classList.contains('rmGT'));const sub=[...hr[1].children].filter(c=>c.offsetParent);
  if(nb&&gt&&sub.length){const a=nb.getBoundingClientRect(),b=gt.getBoundingClientRect(),c=Math.max(...sub.map(x=>x.getBoundingClientRect().bottom));
   if(Math.abs(a.top-b.top)>0.6||Math.abs(a.bottom-c)>0.6)bad.push('κεφαλίδα ομάδας ('+(gt.textContent||'').trim().slice(0,20)+') δεν ταιριάζει με τη γειτονική στήλη: '+(a.bottom-c).toFixed(1)+'px')}}
 t.querySelectorAll('th,td').forEach(c=>{if(!c.offsetParent||!c.textContent.trim())return;if(c.scrollHeight>c.clientHeight+1||c.scrollWidth>c.clientWidth+1)bad.push('κομμένο κείμενο: «'+c.textContent.trim().slice(0,24)+'» ('+c.scrollWidth+'x'+c.scrollHeight+' σε '+c.clientWidth+'x'+c.clientHeight+')')});
 // --- πάχος/χρώμα γραμμών: μέσα και έξω από ομάδες ίδια τιμή (εκτός από το ίδιο το περίγραμμα της ομάδας = box-shadow/::after)
 const edge=c=>{const s=getComputedStyle(c);return ['Top','Right','Bottom','Left'].map(k=>s['border'+k+'Style']==='none'||s['border'+k+'Width']==='0px'?'-':s['border'+k+'Width']+' '+s['border'+k+'Color']).join(' | ')};
 t.querySelectorAll('tr').forEach(tr=>{const cs=[...tr.children].filter(c=>c.offsetParent&&c.rowSpan<=1&&c.colSpan<=1&&!c.classList.contains('stkTotal')&&c!==tr.children[0]);
  const seen={};cs.forEach(c=>{const e=edge(c);(seen[e]=seen[e]||[]).push(c)});
  const keys=Object.keys(seen);if(keys.length>1){const main=keys.sort((a,b)=>seen[b].length-seen[a].length)[0];keys.filter(k=>k!==main).forEach(k=>bad.push('διαφορετικές γραμμές σε γραμμή «'+(tr.children[0].textContent||'').trim().slice(0,16)+'»: '+k+' αντί '+main+' ('+seen[k].length+' κελιά, π.χ. «'+seen[k][0].textContent.trim().slice(0,14)+'»)'))}});
 // η πρώτη υποστήλη κάθε ομάδας πρέπει να έχει την αριστερή γραμμή του περιγράμματος, η τελευταία τη δεξιά, ο τίτλος και τα τρία
 t.querySelectorAll('#readyMatHead th.rmGL,#readyMatHead th.rmGT').forEach(c=>{if(!c.offsetParent)return;if(getComputedStyle(c).boxShadow==='none')bad.push('λείπει το περίγραμμα ομάδας από την επικεφαλίδα «'+c.textContent.trim().slice(0,16)+'»')});
 t.querySelectorAll('#readyMatHead th.rmGR').forEach(c=>{if(c.offsetParent&&getComputedStyle(c).boxShadow==='none')bad.push('λείπει το δεξί περίγραμμα ομάδας από «'+c.textContent.trim().slice(0,16)+'»')});
 return bad})()"""


WORDJS = """(()=>{const bad=[];
 // λέξη που δεν χωράει ολόκληρη στην επικεφαλίδα (σπάει στη μέση) — μέτρηση με canvas
 const cv=document.createElement('canvas').getContext('2d');
 document.querySelectorAll('#readyMatHead th,#readyPressHead th,#readyCommHead th').forEach(c=>{if(!c.offsetParent||!c.textContent.trim())return;const s=getComputedStyle(c);cv.font=s.fontStyle+' '+s.fontWeight+' '+s.fontSize+' '+s.fontFamily;
  const avail=c.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),ls=parseFloat(s.letterSpacing)||0;
  c.textContent.replace(/[⌄›]/g,'').trim().split(' ').filter(Boolean).forEach(w=>{const ww=cv.measureText(s.textTransform==='uppercase'?w.toUpperCase():w).width+ls*w.length;if(ww>avail+1)bad.push('λέξη που δεν χωράει στην επικεφαλίδα: «'+w+'» ('+Math.round(ww)+'px σε '+Math.round(avail)+'px)')})});
 return bad})()"""

def run(B, groups=('AXIOPOIISIMA', 'EIDIKIS_DIACHEIRISIS', 'APORRIPSI', 'PLAKETES'), zooms=(0.85, 1, 1.25)):
    problems = []
    with sync_playwright() as p:
        b = launch(p)
        try:
            pg = b.new_page(viewport={'width': 1366, 'height': 800})
            pg.goto(B + '/', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
            pg.click('.nav button[data-view="ready"]'); pg.wait_for_timeout(1200)
            pg.evaluate("readyState.period='month';readyState.cursor=new Date(2026,8,1)")
            for g in groups:
                pg.evaluate("(g)=>document.querySelector('#readyGroupTabs [data-readygroup=\"'+g+'\"]').click()", g); pg.wait_for_timeout(1500)
                pg.evaluate("(()=>{[...document.querySelectorAll('#readyMatHead [data-rmtoggle]')].forEach(t=>readyState.colOpen.add(t.dataset.rmtoggle));renderReadyMaterials()})()")
                for z in zooms:
                    pg.evaluate("(z)=>{document.documentElement.style.setProperty('--vz',z);window.dispatchEvent(new Event('resize'))}", z); pg.wait_for_timeout(500)
                    for m in pg.evaluate(JS)+pg.evaluate(WORDJS):
                        problems.append(f'[{g} / {int(z*100)}%] {m}')
            # Πρέσα / Εμπορικά: επικεφαλίδες χωρίς κομμένο ή ξεχειλισμένο κείμενο (αναδίπλωση μέσα στο κελί)
            for g, hid in (('PRESS', 'readyPressHead'), ('COMMERCIAL', 'readyCommHead')):
                pg.evaluate("(g)=>document.querySelector('#readyGroupTabs [data-readygroup=\"'+g+'\"]').click()", g); pg.wait_for_timeout(1500)
                for z in zooms:
                    pg.evaluate("(z)=>{document.documentElement.style.setProperty('--vz',z);window.dispatchEvent(new Event('resize'))}", z); pg.wait_for_timeout(400)
                    for m in pg.evaluate(WORDJS):
                        problems.append(f'[{g} / {int(z*100)}%] {m}')
                    for m in pg.evaluate("(id)=>[...document.querySelectorAll('#'+id+' th')].filter(c=>c.offsetParent&&c.textContent.trim()&&(c.scrollHeight>c.clientHeight+1||c.scrollWidth>c.clientWidth+1)).map(c=>'κομμένο κείμενο επικεφαλίδας: «'+c.textContent.trim().slice(0,24)+'»')", hid):
                        problems.append(f'[{g} / {int(z*100)}%] {m}')
            pg.evaluate("document.documentElement.style.setProperty('--vz',1)")
        finally:
            b.close()
    for m in problems:
        print(m)
    return len(problems)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('ΠΡΟΒΛΗΜΑΤΑ ΟΜΑΔΩΝ ΣΤΗΛΩΝ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
