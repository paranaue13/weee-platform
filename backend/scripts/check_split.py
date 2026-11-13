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


# ======================= ΣΑΡΩΣΗ ΠΛΑΤΩΝ (B1): όλες οι σελίδες/υποκαρτέλες × πολλά πλάτη × μενού ανοιχτό / εικονίδια =======================
# Εντοπίζει: κομμένα στοιχεία, λευκή σελίδα, επικαλύψεις, πίνακες χωρίς scroll όταν δεν χωράνε, μισή γραμμή κάτω από sticky κεφαλίδα, τρεμόπαιγμα (αλλαγές πλάτους/διάταξης).
# Χρήση: python check_split.py [http://127.0.0.1:8000] scan [γρήγορο]   — τυπώνει ΜΟΝΟ προβλήματα, αλλιώς «0 προβλήματα».
SCAN_WIDTHS = [900, 1100, 1300, 1600, 1920]
SCAN_VIEWS = ['dashboard', 'receipts', 'weee', 'production', 'ready', 'loading', 'inventory', 'galaxy', 'reports', 'master']
SCAN_JS = """()=>{
 const out=[],iw=innerWidth,de=document.documentElement;
 const vis=e=>{const r=e.getBoundingClientRect();if(r.width<2||r.height<2)return false;const cs=getComputedStyle(e);return cs.visibility!=='hidden'&&cs.display!=='none'&&e.offsetParent!==null};
 const nm=e=>((e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/ +/).slice(0,2).join('.'):''))||e.tagName;
 const tx=e=>(e.innerText||e.value||e.placeholder||e.getAttribute('aria-label')||e.title||'').trim().replace(/\\s+/g,' ').slice(0,24);
 const main=document.querySelector('.content');
 if(!main||main.getBoundingClientRect().height<60||!((main.innerText||'').trim()))out.push('λευκή σελίδα (κενό περιεχόμενο)');
 else if(main.getBoundingClientRect().top>innerHeight*0.6||main.getBoundingClientRect().right<60)out.push('λευκή σελίδα (το περιεχόμενο ξεκινά εκτός οθόνης: '+Math.round(main.getBoundingClientRect().left)+','+Math.round(main.getBoundingClientRect().top)+')');
 if(de.scrollWidth>iw+1)out.push('οριζόντιο scroll όλης της σελίδας ('+de.scrollWidth+' > '+iw+')');
 const scrollable=e=>/auto|scroll/.test(getComputedStyle(e).overflowX);
 const clipper=e=>/hidden|clip/.test(getComputedStyle(e).overflowX);
 const root=main||document.body;
 const items=[...root.querySelectorAll('button,.btn,input:not([type=checkbox]):not([type=radio]),select,.readyGroupTab,.productionTab,.mtab,.weeeTabBtn,.receiptMode')].filter(e=>vis(e)&&!e.closest('table,.hidden,.popover,.autoCloseMenu,.periodPickerDropdown,#floatingEditor,.floatPanel,.cxOverlay,[role=listbox],[aria-hidden=true]'));
 // κομμένα στοιχεία: εκτός οθόνης ή κομμένα από πρόγονο με overflow:hidden (χωρίς scroll)
 items.forEach(e=>{const r=e.getBoundingClientRect();let p=e.parentElement,inScroll=false,cut=null;
  while(p&&p!==document.body){if(scrollable(p)&&p.scrollWidth>p.clientWidth+2){inScroll=true;break}
   if(clipper(p)&&!scrollable(p)){const q=p.getBoundingClientRect();if(q.width>2&&(r.right>q.right+2||r.left<q.left-2)){cut=p;break}}
   p=p.parentElement}
  if(cut)out.push('κομμένο στοιχείο «'+tx(e)+'» ('+nm(e)+') από '+nm(cut));
  else if(!inScroll&&(r.right>iw+1||r.left<-1))out.push('στοιχείο «'+tx(e)+'» ('+nm(e)+') εκτός οθόνης ('+Math.round(r.left)+'..'+Math.round(r.right)+' από '+iw+')')});
 // επικαλύψεις διαδραστικών στοιχείων
 const ov=new Set();
 for(let i=0;i<items.length;i++)for(let j=i+1;j<items.length;j++){const a=items[i],b=items[j];if(a.contains(b)||b.contains(a))continue;
  const A=a.getBoundingClientRect(),B=b.getBoundingClientRect();const w=Math.min(A.right,B.right)-Math.max(A.left,B.left),h=Math.min(A.bottom,B.bottom)-Math.max(A.top,B.top);
  if(w>3&&h>3&&!(a.closest('.pfCb')&&a.closest('.pfCb')===b.closest('.pfCb'))){const k=tx(a)+'|'+tx(b);if(!ov.has(k)){ov.add(k);out.push('επικάλυψη «'+tx(a)+'» ('+nm(a)+') με «'+tx(b)+'» ('+nm(b)+')')}}}
 // πίνακες/πλαίσια: περιεχόμενο που δεν χωράει πρέπει να έχει οριζόντιο scroll
 [...root.querySelectorAll('.prodTableWrap,.tablewrap,.registryTableWrap,.sfWrap,.sectionTableWrap,.lmWrap,.mtGrid,.shipHistWrap,.mtBody')].filter(vis).forEach(w=>{
  if(w.classList.contains('mtBody'))return;
  const t=w.querySelector('table');const cw=w.clientWidth,sw=w.scrollWidth;
  const anc=(()=>{let q=w.parentElement;while(q&&q!==document.body){if(scrollable(q)&&q.scrollWidth>q.clientWidth+2)return true;q=q.parentElement}return false})();
  if(sw>cw+2&&!scrollable(w)&&!anc)out.push('πίνακας '+nm(w)+' δεν χωράει ('+sw+' > '+cw+') και δεν έχει οριζόντιο scroll');
  if(t&&scrollable(w)){const tr=t.getBoundingClientRect(),wr=w.getBoundingClientRect();if(tr.width<wr.width-3&&getComputedStyle(t).tableLayout!=='fixed'&&t.rows.length>1&&!w.classList.contains('mtGrid')&&!t.closest('[data-nofill]'))out.push('πίνακας '+nm(w)+' δεν γεμίζει το πλάτος του πλαισίου ('+Math.round(tr.width)+' < '+Math.round(wr.width)+')')}
  // μισή γραμμή κάτω από sticky κεφαλίδα: στο scroll 0 η πρώτη γραμμή δεν πρέπει να χώνεται κάτω από τη κεφαλίδα
  if(t&&t.tHead&&t.tHead.rows[0]&&t.tHead.rows[0].cells[0]&&t.tBodies[0]&&getComputedStyle(t.tHead.rows[0].cells[0]).position==='sticky'){w.scrollTop=0;const hb=Math.max(...[...t.tHead.rows].map(r=>r.getBoundingClientRect().bottom));
   const first=[...t.tBodies[0].rows].find(r=>r.getBoundingClientRect().height>4&&getComputedStyle(r).display!=='none');
   if(first){const fr=first.getBoundingClientRect();if(fr.top<hb-2&&fr.bottom>hb+2)out.push('μισή γραμμή κάτω από sticky κεφαλίδα στον πίνακα '+nm(w)+' (γραμμή '+Math.round(fr.top)+'..'+Math.round(fr.bottom)+', κεφαλίδα τέλος '+Math.round(hb)+')')}}
 });
 return [...new Set(out)]}"""

FLICKER_JS = """()=>new Promise(res=>{const s=[];let n=0;const t0=performance.now();
 const grab=()=>{const m=document.querySelector('.content'),sh=document.querySelector('.shell');s.push([de().clientWidth,m?Math.round(m.getBoundingClientRect().width):0,sh?getComputedStyle(sh).gridTemplateColumns:'',m&&(m.innerText||'').trim().length>0?1:0,document.body.scrollHeight])};
 const de=()=>document.documentElement;
 const iv=setInterval(()=>{grab();if(performance.now()-t0>1400){clearInterval(iv);
   let ch=0;for(let i=1;i<s.length;i++)if(s[i][0]!==s[i-1][0]||s[i][1]!==s[i-1][1]||s[i][2]!==s[i-1][2])ch++;
   const white=s.filter(x=>!x[3]).length;
   res({changes:ch,white,n:s.length,widths:[...new Set(s.map(x=>x[0]+'/'+x[1]))].slice(0,4)})}},40)})"""


def _enable_icons(pg, on):
    pg.evaluate("on=>{document.body.classList.toggle('sideAuto',!!on)}", on)


def scan(base='http://127.0.0.1:8000', quick=False):
    total = 0
    widths = [1100, 1600] if quick else SCAN_WIDTHS
    with sync_playwright() as p:
        b = launch(p)
        try:
            for W in widths:
                for icons in (False, True):
                    ctx = b.new_context(viewport={'width': W, 'height': 800}); pg = ctx.new_page()
                    try:
                        pg.goto(base + '/', wait_until='networkidle', timeout=60000); pg.wait_for_selector('#loginBtn', state='visible', timeout=40000)
                        pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=60000)
                    except Exception as e:
                        total += 1; print(f'[{W}px] ΣΦΑΛΜΑ σύνδεσης: {str(e)[:80]}'); ctx.close(); continue
                    _enable_icons(pg, icons); pg.wait_for_timeout(300)
                    tag = f'{W}px · {"μενού εικονίδια" if icons else "μενού ανοιχτό"}'
                    for v in SCAN_VIEWS:
                        try:
                            pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1400)
                            n = max(pg.evaluate("([v,sel])=>{const s=document.getElementById(v);if(!s)return 0;return [...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table')&&!b.closest('.hidden')).length}", [v, GEN]), 1)
                            for i in range(min(n, 12)):
                                if n > 1:
                                    pg.evaluate("([v,sel,i])=>{const s=document.getElementById(v);const l=[...s.querySelectorAll(sel)].filter(b=>b.offsetParent&&!b.closest('table')&&!b.closest('.hidden'));if(l[i])l[i].click()}", [v, GEN, i]); pg.wait_for_timeout(1100)
                                for m in pg.evaluate(SCAN_JS):
                                    total += 1; print(f'[{tag} · {v} / καρτέλα {i}] {m}')
                        except Exception as e:
                            total += 1; print(f'[{tag} · {v}] ΣΦΑΛΜΑ ελέγχου: {str(e)[:100]}')
                    ctx.close()
            # τρεμόπαιγμα: πλάτη γύρω από τα όρια διάταξης (980/1050/1100...), μενού εικονίδια, σελίδες Παραγωγή/Αρχική/Αποθήκη ΑΗΗΕ/Φορτώσεις
            flick_w = [960, 975, 985, 1000, 1045, 1055, 1095, 1105, 1195, 1205] if not quick else [975, 985]
            ctx = b.new_context(viewport={'width': 1300, 'height': 800}); pg = ctx.new_page()
            pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
            pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=20000)
            for icons in (True, False):
                _enable_icons(pg, icons)
                for v in ('dashboard', 'production', 'weee', 'loading'):
                    pg.evaluate(f"show('{v}')"); pg.wait_for_timeout(1200)
                    for W in flick_w:
                        pg.set_viewport_size({'width': W, 'height': 800}); r = pg.evaluate(FLICKER_JS)
                        if r['changes'] > 1 or r['white']:
                            total += 1; print(f'[τρεμόπαιγμα · {W}px · {"εικονίδια" if icons else "ανοιχτό"} · {v}] αλλαγές διάταξης {r["changes"]} σε 1,4s, λευκά δείγματα {r["white"]}, πλάτη {r["widths"]}')
            ctx.close()
        finally:
            b.close()
    print(f'{total} προβλήματα' if total else '0 προβλήματα')
    return total


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith('http') else 'http://127.0.0.1:8000'
    if 'scan' in sys.argv:
        sys.exit(1 if scan(base, 'γρήγορο' in sys.argv) else 0)
    print('ΠΡΟΒΛΗΜΑΤΑ ΠΟΛΛΑΠΛΗΣ ΟΘΟΝΗΣ:', run(base, 'γρήγορο' in sys.argv or 'μικρό' in sys.argv, 'μικρό' in sys.argv))
