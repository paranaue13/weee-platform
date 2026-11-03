"""Έλεγχος οπτικών λαθών σε πίνακες με σταθερά σημεία (επικεφαλίδα, πρώτες στήλες, κάτω γραμμές συνόλου).
Για κάθε ορατό πίνακα prodTable/tablewrap, σε θέσεις scroll πάνω/κάτω/αριστερά/δεξιά και με ανοιχτές/κλειστές ομάδες:
 (1) κάθε σταθερό κελί (th/td με position:sticky) έχει αδιάφανο φόντο,
 (2) το κέντρο κάθε σταθερού κελιού ζωγραφίζεται από το ίδιο το κελί (τίποτα δεν περνά από πάνω του: elementFromPoint),
 (3) η τελευταία γραμμή δεδομένων φαίνεται ολόκληρη στο τέρμα κάτω (δεν κόβεται από τις κάτω σταθερές γραμμές).
Τυπώνει μόνο προβλήματα. Μόνο ανάγνωση. Χρήση: python check_sticky_paint.py [http://127.0.0.1:8000]"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch

JS = """(sel)=>{
 const out=[],nm=e=>(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/ +/).slice(0,2).join('.'):'')||e.tagName;
 const root=[...document.querySelectorAll(sel)].find(e=>e.offsetParent&&e.getBoundingClientRect().height>40);if(!root)return out;
 const wraps=[...root.querySelectorAll('.prodTableWrap,.tablewrap')].filter(w=>w.offsetParent&&w.getBoundingClientRect().height>60&&w.querySelector('table'));
 const opaque=c=>{const m=c.match(/rgba?\\(([^)]+)\\)/);if(!m)return false;const p=m[1].split(',').map(Number);return p.length<4||p[3]>=0.99};
 const txt=e=>(e.innerText||'').trim().slice(0,14);
 const paint=(w,when)=>{
  const wr=w.getBoundingClientRect(),vz=(w.offsetHeight>0?wr.height/w.offsetHeight:1);
  const tb=w.querySelector('table'),hb=tb&&tb.tHead?tb.tHead.getBoundingClientRect():null,fb=tb&&tb.tFoot&&tb.tFoot.rows.length?tb.tFoot.getBoundingClientRect():null;
  const inBand=c=>{const r=c.getBoundingClientRect(),y=r.top+r.height/2;return (hb&&y<hb.bottom&&y>hb.top-2)||(fb&&y>fb.top&&y<fb.bottom)};
  const cells=[...w.querySelectorAll('thead th,tfoot td,tfoot th,tbody td:first-child,tbody th:first-child')].filter(c=>c.offsetParent&&getComputedStyle(c).position==='sticky'&&(c.closest('thead,tfoot')||!inBand(c)));
  cells.forEach(c=>{
   const cs=getComputedStyle(c),r=c.getBoundingClientRect();
   if(r.width<4||r.height<4)return;
   // κελί που βγαίνει εκτός ορατού πλαισίου δεν ελέγχεται
   const x=r.left+r.width/2,y=r.top+r.height/2;if(x<wr.left+2||x>wr.right-2||y<wr.top+2||y>wr.bottom-2)return;
   if(!opaque(cs.backgroundColor)&&!c.querySelector('input,button'))out.push(nm(w)+' ['+when+']: διαφανές φόντο στο σταθερό κελί «'+txt(c)+'»');
   if(!c.closest('thead,tfoot'))return;
   const top=document.elementFromPoint(x,y);
   if(top&&top!==c&&!c.contains(top)&&!top.contains(c)&&(!top.closest('thead,tfoot')||(!c.closest('thead,tfoot')&&false)))out.push(nm(w)+' ['+when+']: το σταθερό κελί «'+txt(c)+'» καλύπτεται από «'+txt(top)+'» ('+nm(top)+')');
  });
 };
 const lastRowCut=(w,when)=>{
  const t=w.querySelector('table');if(!t||!t.tBodies.length)return;
  const rows=[...t.tBodies[0].rows].filter(r=>r.offsetParent&&r.cells.length&&!r.classList.contains('tFill'));if(!rows.length)return;
  const last=rows[rows.length-1],lr=last.getBoundingClientRect();
  const foot=t.tFoot?[...t.tFoot.rows].filter(r=>r.offsetParent&&r.cells.length):[];
  if(foot.length){const ft=Math.min(...foot.map(r=>r.getBoundingClientRect().top));if(lr.bottom>ft+1.5)out.push(nm(w)+' ['+when+']: η τελευταία γραμμή δεδομένων «'+txt(last.cells[0])+'» κόβεται από τις σταθερές γραμμές κάτω ('+Math.round(lr.bottom-ft)+'px)')}
 };
 // κελί-κουμπί: το κουμπί πρέπει να καλύπτει ολόκληρο το κελί (το πλαίσιο επιλογής/hover να πιάνει τις άκρες του κελιού)
 root.querySelectorAll('td>button:only-child,td>.corrBtn').forEach(bt=>{const td=bt.parentElement;if(!td.offsetParent||!bt.offsetParent)return;const a=td.getBoundingClientRect(),b=bt.getBoundingClientRect();if(a.width<20)return;
  if(Math.abs(a.left-b.left)>1.5||Math.abs(a.right-b.right)>1.5||Math.abs(a.top-b.top)>1.5||Math.abs(a.bottom-b.bottom)>1.5)out.push(nm(td.closest('table'))+': το κουμπί του κελιού «'+txt(td)+'» δεν καλύπτει όλο το κελί (αριστερά '+Math.round(b.left-a.left)+', δεξιά '+Math.round(a.right-b.right)+', πάνω '+Math.round(b.top-a.top)+', κάτω '+Math.round(a.bottom-b.bottom)+')')});
 wraps.forEach(w=>{
  const sw=w.scrollWidth>w.clientWidth+2,sh=w.scrollHeight>w.clientHeight+2;
  const pos=[['πάνω-αριστερά',0,0]];
  if(sh)pos.push(['κάτω-αριστερά',0,1e9]);
  if(sw)pos.push(['πάνω-δεξιά',1e9,0]);
  if(sw&&sh)pos.push(['κάτω-δεξιά',1e9,1e9]);
  if(sh)pos.push(['μέση',0,Math.max(0,(w.scrollHeight-w.clientHeight)/2)]);
  pos.forEach(([n,x,y])=>{w.scrollLeft=x;w.scrollTop=y;paint(w,n);if(y>0&&y>=w.scrollHeight-w.clientHeight-2)lastRowCut(w,n)});
  w.scrollLeft=0;w.scrollTop=0;
 });
 return out}"""

VIEWS = [
    ('production', '#production', ['[data-prodtab=weee]'], True),
    ('ready', '#ready', ['.readyGroupTab'], True),
]


def run(base='http://127.0.0.1:8000'):
    total = 0
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (W, H) in [(1366, 768), (1920, 1080)]:
                pg = b.new_page(viewport={'width': W, 'height': H})
                pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                for (v, sel, tabs, groups) in VIEWS:
                    pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1500)
                    pg.evaluate("(()=>{try{if(typeof readyState!=='undefined')readyState.cursor=new Date('2026-09-15T12:00:00');if(typeof prodState!=='undefined')prodState.cursor=new Date('2026-09-15T12:00:00')}catch(e){}})()")
                    pg.evaluate("(()=>{try{if(document.getElementById('production')&&!document.getElementById('production').classList.contains('hidden'))loadProduction();else readyRefreshActive()}catch(e){}})()"); pg.wait_for_timeout(2500)
                    n = max(pg.evaluate(f"[...document.querySelectorAll('{sel} {tabs[0]}')].filter(b=>b.offsetParent).length"), 1)
                    for i in range(n):
                        pg.evaluate(f"(()=>{{let l=[...document.querySelectorAll('{sel} {tabs[0]}')].filter(b=>b.offsetParent);if(l[{i}])l[{i}].click()}})()"); pg.wait_for_timeout(1800)
                        for state in ('κλειστές ομάδες', 'ανοιχτές ομάδες'):
                            if state == 'ανοιχτές ομάδες':
                                pg.evaluate(f"document.querySelectorAll('{sel} .prodMajorHead:not(.expanded), {sel} th.rmGTop:not(.expanded), {sel} th.thGroup:not(.expanded)').forEach(x=>{{if(x.offsetParent)x.click()}})"); pg.wait_for_timeout(1500)
                            for msg in pg.evaluate(JS, sel):
                                total += 1; print(f'[{W}x{H} · {v} / καρτέλα {i} / {state}] {msg}')
                pg.close()
        finally:
            b.close()
    return total


if __name__ == '__main__':
    print('ΠΡΟΒΛΗΜΑΤΑ ΣΤΑΘΕΡΩΝ ΣΗΜΕΙΩΝ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
