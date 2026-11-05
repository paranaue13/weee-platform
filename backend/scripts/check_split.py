"""Έλεγχος πολλαπλής οθόνης (split screen: κάθετο, οριζόντιο, 3 στήλες, 2×2) σε όλες τις σελίδες και υποκαρτέλες.
Σε κάθε οθόνη (iframe) ελέγχει:
 (1) η σελίδα της οθόνης δεν έχει δικό της οριζόντιο scroll/υπερχείλιση (ό,τι δεν χωράει κυλά ΜΕΣΑ στον πίνακα),
 (2) η μπάρα «Μέγεθος» υπάρχει, είναι αδιάφανη, πιάνει όλο το πλάτος της οθόνης και τελειώνει ακριβώς στο κάτω όριό της (χωρίς γκρι ορθογώνια),
 (3) κάθε πίνακας με στήλες που δεν χωράνε έχει οριζόντιο scroll, το πλαίσιό του είναι ολόκληρο μέσα στην οθόνη και στο τέρμα δεξιά φαίνεται η ΤΕΛΕΥΤΑΙΑ στήλη,
 (4) το κάτω μέρος του πλαισίου (και η μπάρα scroll του) δεν καλύπτεται από τη μπάρα «Μέγεθος»,
 (5) οι οθόνες της ίδιας σειράς τελειώνουν στο ίδιο ύψος.
Επίσης αλλάζει το μέγεθος γραμμάτων («Μέγεθος») και το πλάτος της οθόνης (σύρσιμο διαχωριστή) και ξαναελέγχει.
Μόνο ανάγνωση. Χρήση: python check_split.py [http://127.0.0.1:8000] [γρήγορο]"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch

GEN = '.tab,.mtab,.productionTab,.weeeTabBtn,.readyGroupTab,.receiptMode,.profileTabBtn'
VIEWS = ['dashboard', 'receipts', 'weee', 'production', 'ready', 'loading', 'inventory', 'galaxy', 'reports', 'master']
SIZES = [(1920, 1080), (1600, 900), (1366, 768)]
LAYOUTS = ['v', 'h', 'c3', 'q']

JS = """(ctx)=>{
 const out=[],iw=innerWidth,ih=innerHeight,de=document.documentElement;
 const nm=e=>(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/ +/).slice(0,2).join('.'):'')||e.tagName;
 if(de.scrollWidth>iw+1)out.push('η σελίδα της οθόνης έχει δικό της οριζόντιο scroll ('+de.scrollWidth+' > '+iw+')');
 const z=document.getElementById('zoomBar');let zt=ih;
 if(!z||getComputedStyle(z).display==='none')out.push('λείπει η μπάρα «Μέγεθος»');
 else{
  const b=z.getBoundingClientRect();zt=b.top;
  if(Math.abs(b.left)>1.5||Math.abs(b.right-iw)>1.5)out.push('η μπάρα «Μέγεθος» δεν πιάνει όλο το πλάτος της οθόνης ('+Math.round(b.left)+'..'+Math.round(b.right)+' από '+iw+')');
  if(Math.abs(b.bottom-ih)>1.5)out.push('η μπάρα «Μέγεθος» δεν τελειώνει στο κάτω όριο της οθόνης (κάτω '+Math.round(b.bottom)+' από '+ih+')');
  const bg=getComputedStyle(z).backgroundColor;if(/rgba\\(.*,\\s*0\\)$/.test(bg))out.push('η μπάρα «Μέγεθος» έχει διαφανές φόντο');
 }
 const wraps=[...document.querySelectorAll('.prodTableWrap,.tablewrap,.registryTableWrap,.sfWrap,.sectionTableWrap,.lmWrap,.mtGrid')].filter(w=>w.offsetParent&&!w.closest('.hidden'));
 // (4) το κάτω μέρος του πλαισίου: μετράται με τη σελίδα της οθόνης κυλισμένη στο τέλος (η μπάρα «Μέγεθος» είναι σταθερή κάτω)
 const dsT=window.scrollY;window.scrollTo(0,1e9);
 wraps.forEach(w=>{let q=w.parentElement,saved=[];while(q&&q!==document.body){if(/auto|scroll/.test(getComputedStyle(q).overflowY)&&q.scrollHeight>q.clientHeight+2){saved.push([q,q.scrollTop]);q.scrollTop=1e9}q=q.parentElement}
  const r=w.getBoundingClientRect();saved.forEach(([e,t])=>{e.scrollTop=t});if(r.width<60||r.height<40)return;
  if(r.height<ih&&r.bottom>zt+1.5&&r.top<zt&&r.bottom-r.top>0&&(document.documentElement.scrollHeight-window.scrollY-ih<=1))out.push(nm(w)+': το κάτω μέρος του πλαισίου (και η μπάρα scroll) καλύπτεται από τη μπάρα «Μέγεθος» ('+Math.round(r.bottom-zt)+'px) ακόμα και στο τέλος της σελίδας')});
 window.scrollTo(0,dsT);
 wraps.forEach(w=>{
  const r=w.getBoundingClientRect();if(r.width<60||r.height<40)return;
  if(r.right>iw+1.5||r.left<-1.5)out.push(nm(w)+': το πλαίσιο του πίνακα βγαίνει εκτός οθόνης ('+Math.round(r.left)+'..'+Math.round(r.right)+' από '+iw+')');
  let sc=w;
  if(!(w.scrollWidth>w.clientWidth+2)){
   // οι στήλες χωράνε στο πλαίσιο· αν όμως το πλαίσιο δεν κόβει, ο πίνακας μπορεί να βγαίνει από αυτό
   const t=w.querySelector('table');if(!t||t.getBoundingClientRect().right<=r.right+2)return;
  }
  if(!/auto|scroll/.test(getComputedStyle(sc).overflowX)){
   let a=w.parentElement;while(a&&a!==document.body&&!(/auto|scroll/.test(getComputedStyle(a).overflowX)&&a.scrollWidth>a.clientWidth+2))a=a.parentElement;
   if(!a||a===document.body){out.push(nm(w)+': οι στήλες δεν χωράνε και δεν υπάρχει οριζόντιο scroll');return}
   sc=a;
  }
  sc.scrollLeft=1e9;
  const cells=[...w.querySelectorAll('thead th, thead td')].filter(c=>c.offsetParent);
  if(cells.length){const last=cells.reduce((a,c)=>c.getBoundingClientRect().right>a.getBoundingClientRect().right?c:a),lr=last.getBoundingClientRect().right,lim=Math.min(sc.getBoundingClientRect().right,iw);
   if(lr>lim+2)out.push(nm(w)+': στο τέρμα δεξιά η τελευταία στήλη «'+(last.innerText||'').trim().slice(0,18)+'» δεν φαίνεται ('+Math.round(lr)+' > '+Math.round(lim)+')')}
  sc.scrollLeft=0;
 });
 return out}"""

SET_Q = """(i)=>{let b=document.querySelector('.sideQuick [data-q="'+i+'"]');if(b&&!b.disabled)b.click();return !!b&&!b.disabled}"""


def panes_of(pg):
    fr = []
    for h in pg.query_selector_all('.splitPane iframe'):
        f = h.content_frame()
        if f:
            fr.append(f)
    return fr


def pane_tabs(f, view):
    return f.evaluate("""([v,sel])=>{const s=document.getElementById(v);if(!s)return 0;return [...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table')).length}""", [view, GEN])


def click_tab(f, view, i):
    f.evaluate("""([v,sel,i])=>{const s=document.getElementById(v);const l=[...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table'));if(l[i])l[i].click()}""", [view, GEN, i])


def host_heights(pg):
    return pg.evaluate("""()=>[...document.querySelectorAll('.splitPane')].map(p=>{let r=p.getBoundingClientRect();return [Math.round(r.top),Math.round(r.bottom)]})""")


def run(base='http://127.0.0.1:8000', quick=False, small=False):
    total = 0
    sizes = SIZES[1:] if small else (SIZES[:1] if quick else SIZES)
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (W, H) in sizes:
                for lay in LAYOUTS:
                    ctx = b.new_context(viewport={'width': W, 'height': H}); pg = ctx.new_page()
                    pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                    pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
                    if not pg.evaluate(SET_Q, lay):
                        print(f'[{W}x{H} · {lay}] η διάταξη δεν χωράει'); ctx.close(); continue
                    pg.wait_for_timeout(2500)
                    fr = panes_of(pg)
                    # οι οθόνες της ίδιας σειράς τελειώνουν στο ίδιο ύψος
                    hs = host_heights(pg); rows = {}
                    for t, bt in hs: rows.setdefault(t, set()).add(bt)
                    for t, s in rows.items():
                        if len(s) > 1:
                            total += 1; print(f'[{W}x{H} · {lay}] οι οθόνες της ίδιας σειράς δεν τελειώνουν στο ίδιο ύψος: {sorted(s)}')
                    for pi, f in enumerate(fr):
                        if quick and pi > 0: break
                        for v in VIEWS:
                            try:
                                f.evaluate(f"show('{v}')"); pg.wait_for_timeout(1500)
                                n = max(pane_tabs(f, v), 1)
                                for i in range(min(n, 12)):
                                    if n > 1 or v in ('ready', 'master', 'production', 'reports'):
                                        click_tab(f, v, i); pg.wait_for_timeout(1400)
                                    for msg in f.evaluate(JS, {}):
                                        total += 1; print(f'[{W}x{H} · {lay} · οθόνη {pi+1} · {v} / καρτέλα {i}] {msg}')
                            except Exception as e:
                                total += 1; print(f'[{W}x{H} · {lay} · οθόνη {pi+1} · {v}] ΣΦΑΛΜΑ ελέγχου: {str(e)[:120]}')
                        # άλλο μέγεθος γραμμάτων σε Υλικά και Μητρώα
                        for zoom in (70, 150):
                            for v, tabsel in (('ready', 0), ('master', 0)):
                                try:
                                    f.evaluate(f"show('{v}')"); pg.wait_for_timeout(1200)
                                    f.evaluate(f"setViewZoom({zoom})"); pg.wait_for_timeout(1500)
                                    for msg in f.evaluate(JS, {}):
                                        total += 1; print(f'[{W}x{H} · {lay} · οθόνη {pi+1} · {v} · μέγεθος {zoom}%] {msg}')
                                    f.evaluate("setViewZoom(100)"); pg.wait_for_timeout(500)
                                except Exception as e:
                                    total += 1; print(f'[{W}x{H} · {lay} · οθόνη {pi+1} · {v} · μέγεθος {zoom}%] ΣΦΑΛΜΑ ελέγχου: {str(e)[:120]}')
                    # αλλαγή πλάτους οθόνης με τον διαχωριστή (σύρσιμο): ξαναελέγχεται ο υπολογισμός
                    if lay in ('v', 'c3', 'q'):
                        try:
                            d = pg.query_selector('.splitDiv.v')
                            if d:
                                bb = d.bounding_box(); pg.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + 40); pg.mouse.down(); pg.mouse.move(bb['x'] + bb['width'] / 2 + 120, bb['y'] + 40, steps=8); pg.mouse.up(); pg.wait_for_timeout(1800)
                                f = panes_of(pg)[0]; f.evaluate("show('ready')"); pg.wait_for_timeout(1500)
                                for msg in f.evaluate(JS, {}):
                                    total += 1; print(f'[{W}x{H} · {lay} · μετά το σύρσιμο διαχωριστή · ready] {msg}')
                        except Exception as e:
                            total += 1; print(f'[{W}x{H} · {lay}] ΣΦΑΛΜΑ σύρσιμου: {str(e)[:120]}')
                    ctx.close()
        finally:
            b.close()
    return total


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('http') else 'http://127.0.0.1:8000'
    print('ΠΡΟΒΛΗΜΑΤΑ ΠΟΛΛΑΠΛΗΣ ΟΘΟΝΗΣ:', run(base, 'γρήγορο' in sys.argv or 'μικρό' in sys.argv, 'μικρό' in sys.argv))
