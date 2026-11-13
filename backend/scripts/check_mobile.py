"""Έλεγχος οθόνης Android (/mobile) σε 360/412/800px: όλες οι ενότητες και βασικά βήματα.
Εντοπίζει: οριζόντια υπερχείλιση, στοιχεία εκτός οθόνης, κομμένα κείμενα κουμπιών, επικαλύψεις. Τυπώνει ΜΟΝΟ προβλήματα, αλλιώς «0 προβλήματα».
Χρήση (ΜΟΝΟ σε server με αντίγραφο δεδομένων): python check_mobile.py http://127.0.0.1:8024"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000').rstrip('/')
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
JS=r"""()=>{const out=[],iw=innerWidth,de=document.documentElement;
 if(de.scrollWidth>iw+1)out.push('οριζόντιο scroll σελίδας '+de.scrollWidth+'>'+iw);
 const vis=e=>{const r=e.getBoundingClientRect();if(r.width<2||r.height<2)return false;const cs=getComputedStyle(e);return cs.visibility!=='hidden'&&cs.display!=='none'&&e.offsetParent!==null};
 const tx=e=>(e.innerText||e.value||e.placeholder||e.getAttribute('aria-label')||'').trim().replace(/\s+/g,' ').slice(0,26);
 const items=[...document.querySelectorAll('#app button,#app input,#app select,#b4Nav button')].filter(e=>vis(e)&&!e.closest('.hidden,#flKb,#b4ModeHold'));
 const scroller=e=>{let p=e.parentElement;while(p&&p!==document.body){const cs=getComputedStyle(p);if(/auto|scroll/.test(cs.overflowX)&&p.scrollWidth>p.clientWidth+2)return true;p=p.parentElement}return false};
 items.forEach(e=>{const r=e.getBoundingClientRect();if((r.right>iw+1||r.left<-1)&&!scroller(e))out.push('εκτός οθόνης «'+tx(e)+'» '+Math.round(r.left)+'..'+Math.round(r.right));
  if(e.tagName==='BUTTON'&&e.scrollWidth>e.clientWidth+2&&getComputedStyle(e).textOverflow!=='ellipsis')out.push('κομμένο κείμενο «'+tx(e)+'» '+e.scrollWidth+'>'+e.clientWidth)});
 const ov=new Set();for(let i=0;i<items.length;i++)for(let j=i+1;j<items.length;j++){const a=items[i],b=items[j];if(a.contains(b)||b.contains(a))continue;
  if(getComputedStyle(a).position==='sticky'||getComputedStyle(b).position==='sticky')continue;
  const A=a.getBoundingClientRect(),B=b.getBoundingClientRect(),w=Math.min(A.right,B.right)-Math.max(A.left,B.left),h=Math.min(A.bottom,B.bottom)-Math.max(A.top,B.top);
  if(w>3&&h>3&&!(a.closest('#b4Nav')&&!b.closest('#b4Nav'))&&!(b.closest('#b4Nav')&&!a.closest('#b4Nav'))){const k=tx(a)+'|'+tx(b);if(!ov.has(k)){ov.add(k);out.push('επικάλυψη «'+tx(a)+'» / «'+tx(b)+'»')}}}
 return out}"""
steps=[('Παραλαβές',None),('Παραλαβές ▸ ημέρα',"document.querySelector('#loadList [data-open]')?.click()"),
 ('Παραγωγή',"document.querySelector('#b4Nav [data-b4s=production]').click()"),('Παραγωγή ▸ τμήμα',"document.querySelector('#flowArea [data-k=unit]')?.click()"),
 ('Παραγωγή ▸ ΜΕΣΟ',"document.querySelector('.flStart[data-f=m]').click()"),('Παραγωγή ▸ ΑΗΗΕ',"document.querySelector('.flStart[data-f=a]').click()"),
 ('Υλικά',"document.querySelector('#b4Nav [data-b4s=materials]').click()"),('Υλικά ▸ κατηγορία',"document.querySelector('#matArea [data-cat]')?.click()"),('Υλικά ▸ υλικό',"document.querySelector('#matArea [data-mat]')?.click()"),('Υλικά ▸ παλέτα',"document.querySelector('#matArea [data-form=PALLET]')?.click()"),
 ('Αποθήκη',"document.querySelector('.matStart[data-m=stock]').click()"),('Αποθήκη ▸ υλικό',"document.querySelector('.b4WhMat')?.click()"),('Απογραφή',"document.querySelector('.matStart[data-m=count]').click()"),
 ('Φορτώσεις',"document.querySelector('#b4Nav [data-b4s=loading]').click()"),('Εργαζόμενοι',"document.getElementById('topDeltioBtn').click()"),('Εργαζόμενοι ▸ γραμμή',"document.querySelector('.dlRow')?.click()"),('Τμήματα',"document.getElementById('deltioDeptBtn').click()")]
total=0
with sync_playwright() as p:
    b = launch(p)
    for W in (360,412,800):
        pg = b.new_page(viewport={'width': W, 'height': 800}, is_mobile=True, has_touch=True)
        pg.on('pageerror', lambda e: print('pageerror', str(e)[:200]))
        pg.goto(BASE+'/mobile', wait_until='networkidle'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(5000)
        for name,js in steps:
            if js: pg.evaluate(js); pg.wait_for_timeout(2200)
            for m in pg.evaluate(JS): total+=1; print(f'[{W}px · {name}] {m}')
        pg.close()
    b.close()
print(f'{total} προβλήματα' if total else '0 προβλήματα')
