"""Έλεγχος της Αποθήκης ΑΗΗΕ με σταθερά σημεία (καρτέλες + κάρτες + τίτλος/διακόπτες + κεφαλίδα πίνακα + πρώτες στήλες).
Σε πολλά πλάτη/ύψη, διατάξεις (καμία, 2 δίπλα, 2 πάνω-κάτω, 3 στήλες, 2×2), μενού ανοιχτό/κρυμμένο, Μήνας/Τρίμηνο/Έτος, Υποκατηγορίες ανοιχτές/κλειστές,
με scroll πάνω/κάτω ΚΑΙ οριζόντιο, ελέγχει:
 (1) καμία γραμμή δεδομένων δεν φαίνεται μέσα στη ζώνη των σταθερών (από την κορυφή του πίνακα ως το κάτω μέρος της σταθερής κεφαλίδας),
 (2) καμία ζώνη με δύο κεφαλίδες πίνακα ταυτόχρονα, (3) οι κάρτες δεν κόβονται, (4) κενό ανάμεσα σε τίτλο και κεφαλίδα (μέγιστο 0,5px),
 (5) οι πρώτες στήλες (κωδικός, περιγραφή) μένουν ορατές στο οριζόντιο scroll, (6) αν το σταθερό κομμάτι πιάνει πάνω από το μισό ύψος του παραθύρου δεν κολλά τίποτα.
Τυπώνει μόνο προβλήματα. Χρήση: python check_weee_sticky.py [http://127.0.0.1:8000] [--quick]"""
import sys
from playwright.sync_api import sync_playwright
from _browser import launch

AUDIT = """async()=>{
 const out=[],v=document.getElementById('weee');if(!v||!v.offsetParent)return ['(η Αποθήκη ΑΗΗΕ δεν φαίνεται)'];
 const sc=(document.getElementById('weeeBody')&&!v.classList.contains('weeeNoStick'))?document.getElementById('weeeBody'):v;
 const vr=()=>sc.getBoundingClientRect(),sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const stick=document.getElementById('weeeStick');
 const pane=document.getElementById('weeeStockPane');
 const secs=[...v.querySelectorAll('#weeeStockPane .weeeSec')].filter(s=>s.offsetParent);
 const maxY=Math.max(0,sc.scrollHeight-sc.clientHeight),maxX=Math.max(0,sc.scrollWidth-sc.clientWidth);
 const ys=[0,Math.round(maxY*.12),Math.round(maxY*.3),Math.round(maxY*.55),Math.round(maxY*.8),maxY];
 const xs=maxX>2?[0,maxX]:[0];
 const noStick=v.classList.contains('weeeNoStick');
 const half=v.getBoundingClientRect().height/2;
 const sticks=getComputedStyle(stick).position==='sticky';
 // (6) όριο μισού ύψους
 const topBand=((stick&&getComputedStyle(stick).position==='sticky')?stick.getBoundingClientRect().height:0)+(secs[0]&&secs[0].querySelector('.weeeSecHd')?secs[0].querySelector('.weeeSecHd').getBoundingClientRect().height:0)+(secs[0]&&secs[0].querySelector('thead')?secs[0].querySelector('thead').getBoundingClientRect().height:0);
 if(topBand>half+1&&(sticks&&!noStick))out.push('το σταθερό κομμάτι ('+Math.round(topBand)+'px) πιάνει πάνω από το μισό ύψος ('+Math.round(half*2)+'px) αλλά κολλά');
 for(const sx of xs)for(const sy of ys){
  sc.scrollLeft=sx;sc.scrollTop=sy;await sleep(60);
  const R=vr(),tag='[scroll '+(sx?'δεξιά ':'')+sy+'/'+maxY+']';
  // ζώνη σταθερών: από την κορυφή του scroll ως το κάτω όριο του τελευταίου κολλημένου στοιχείου
  let bottom=R.top;const kept=[];
  if(stick&&getComputedStyle(stick).position==='sticky'){const b=stick.getBoundingClientRect();if(b.top<=R.top+1.5){bottom=Math.max(bottom,b.bottom);kept.push(stick)}}
  secs.forEach(s=>{const hd=s.querySelector('.weeeSecHd'),th=s.querySelector('thead th');
    if(hd&&getComputedStyle(hd).position==='sticky'){const b=hd.getBoundingClientRect();if(b.top<=bottom+1.5&&b.bottom>bottom){bottom=Math.max(bottom,b.bottom);kept.push(hd)}}
    if(th&&getComputedStyle(th).position==='sticky'){const b=th.getBoundingClientRect();if(b.top<=bottom+1.5&&b.bottom>bottom&&b.top>=R.top){bottom=Math.max(bottom,b.bottom);kept.push(th)}}});
  const top=Math.max(R.top,0);
  // (1) δεδομένα μέσα στη ζώνη
  const bad=new Set();
  for(let y=top+2;y<bottom-1;y+=5)for(const x of [R.left+6,R.left+R.width*.33,R.left+R.width*.66,R.right-18]){
    const e=document.elementFromPoint(x,y);if(!e)continue;
    if(e.closest('#weeeStick,.weeeSecHd,thead'))continue;
    if(e===v)continue;
    if(e.closest('td'))bad.add('«'+(e.closest('td').innerText||'').trim().slice(0,14)+'»')}
  if(bad.size)out.push(tag+' δεδομένα μέσα στα σταθερά: '+[...bad].slice(0,4).join(', '));
  // (2) δύο κεφαλίδες πίνακα ταυτόχρονα μέσα στη ζώνη των σταθερών (όσα φαίνονται πραγματικά, όχι όσα καλύπτονται)
  const seenHeads=new Map();
  for(let y=top+2;y<bottom-1;y+=4)for(const x of [R.left+6,R.left+R.width*.5]){const e=document.elementFromPoint(x,y);const t=e&&e.closest('#weee thead');if(t&&!seenHeads.has(t))seenHeads.set(t,Math.round(y-R.top)+'px')}
  // στιγμή παράδοσης: ο πρώτος πίνακας τελειώνει ακριβώς κάτω από την κολλημένη κεφαλίδα του και ο επόμενος παίρνει τη θέση του (επιτρέπεται)
  const handoff=seenHeads.size===2&&[...seenHeads.keys()].some(t=>{const tb=t.closest('table').getBoundingClientRect(),h=t.getBoundingClientRect();const th=t.querySelector('th').getBoundingClientRect();return tb.bottom<=th.bottom+3});
  if(seenHeads.size>1&&kept.length&&!handoff)out.push(tag+' φαίνονται '+seenHeads.size+' κεφαλίδες πίνακα ταυτόχρονα στη ζώνη ('+[...seenHeads].map(([t,y])=>t.closest('table').id+'@'+y).join(', ')+', ζώνη '+Math.round(top-R.top)+'–'+Math.round(bottom-R.top)+')');
  // (3) κάρτες
  const cards=[...document.querySelectorAll('#weeeKpis > *')].filter(c=>c.offsetParent);
  if(!v.classList.contains('weeeNoStick'))cards.forEach(c=>{const b=c.getBoundingClientRect();if(b.height<8)return;
    const sb=stick.getBoundingClientRect();
    if(getComputedStyle(stick).position==='sticky'&&b.top<R.top-0.5)out.push(tag+' κάρτα κομμένη στην κορυφή');
    const e=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);
    if(e&&!c.contains(e)&&!e.contains(c)&&sb.top<=R.top+1.5)out.push(tag+' κάρτα καλύπτεται από «'+(e.className||e.tagName)+'»')});
  // (4) κενό ανάμεσα σε κολλημένο τίτλο και κολλημένη κεφαλίδα
  secs.forEach(s=>{const hd=s.querySelector('.weeeSecHd'),th=s.querySelector('thead th');if(!hd||!th||getComputedStyle(hd).position!=='sticky'||getComputedStyle(th).position!=='sticky')return;
    const a=hd.getBoundingClientRect(),b=th.getBoundingClientRect();
    if(Math.abs(a.top-(stick?stick.getBoundingClientRect().bottom:R.top))<1.2&&b.top>a.bottom-3&&b.top<a.bottom+4&&b.top-a.bottom>1.2)out.push(tag+' κενό '+(b.top-a.bottom).toFixed(2)+'px ανάμεσα στον τίτλο και την κεφαλίδα')});
  // (5) πρώτες στήλες στο οριζόντιο scroll
  if(sx>0){secs.forEach(s=>{const t=s.querySelector('tbody tr td:first-child'),th=s.querySelector('thead th:first-child');
    [t,th].forEach(e=>{if(!e||!e.offsetParent)return;const b=e.getBoundingClientRect();if(b.bottom>top&&b.top<R.bottom&&b.right<R.left+10)out.push(tag+' η πρώτη στήλη («'+(e.innerText||'').trim().slice(0,10)+'») δεν μένει ορατή στο οριζόντιο scroll')})})}
 }
 sc.scrollLeft=0;sc.scrollTop=0;
 return [...new Set(out)];
}"""



def wait_rows(page):
    """Περιμένει να γεμίσει ο πίνακας (η φόρτωση παίρνει μερικά δευτερόλεπτα)."""
    try:
        page.wait_for_function("document.querySelectorAll('#weeeProcessRows tr').length>3&&!document.querySelector('#weeeProcessRows .muted')", timeout=45000)
    except Exception:
        pass
    page.wait_for_timeout(900)


def audit_page(page, label, quick):
    """page: Page ή Frame. Επιστρέφει το πλήθος προβλημάτων."""
    n = 0
    page.evaluate("show('weee')"); page.wait_for_timeout(900)
    page.evaluate("weeeDay='2026-03-15'")                      # μήνας με δεδομένα (γεμάτοι πίνακες)
    combos = [('month', False)] if quick else [('month', False), ('month', True), ('quarter', False), ('year', True)]
    for per, subs in combos:
        page.evaluate(f"(()=>{{document.querySelector('[data-weeeperiod=\"{per}\"]').click()}})()"); wait_rows(page)
        page.evaluate(f"(()=>{{const s=document.getElementById('weeeSwSub');if(s&&s.checked!=={str(subs).lower()})s.click();}})()"); page.wait_for_timeout(1800)
        for msg in page.evaluate(AUDIT):
            n += 1; print(f'[{label} · {per}{" · υποκατηγορίες" if subs else ""}] {msg}')
    return n


def run(base='http://127.0.0.1:8000', quick=False, only=None):
    """quick: λίγες ρυθμίσεις (μέσα στο check_tables)· πλήρης: όλα τα πλάτη/ύψη, όλες οι διατάξεις, μενού ανοιχτό/κρυμμένο, Μήνας/Τρίμηνο/Έτος, υποκατηγορίες."""
    total = 0
    if quick:
        jobs = [('none', 750, 440, False), ('none', 1020, 900, False), ('none', 1366, 768, False), ('h', 1366, 768, False)]
    else:
        jobs = [('none', w, h, hide) for (w, h) in [(650, 700), (750, 440), (900, 700), (1020, 900), (1366, 440), (1366, 768), (1920, 1000)] for hide in (False, True)]
        jobs += [(lay, w, h, False) for lay in ('v', 'h', 'c3', 'q') for (w, h) in [(1366, 440), (1600, 900), (1920, 1000)]]
        jobs += [(lay, 1920, 1000, True) for lay in ('v', 'h', 'c3', 'q')]
    if only == 'layouts': jobs = [j for j in jobs if j[0] != 'none']
    elif only == 'none': jobs = [j for j in jobs if j[0] == 'none']
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (lay, W, H, hide) in jobs:
                ctx = b.new_context(viewport={'width': W, 'height': H}); pg = ctx.new_page()      # νέο περιβάλλον ανά δοκιμή: οι ρυθμίσεις (μενού, διάταξη) δεν περνούν στην επόμενη
                try:
                    pg.goto(base + '/', wait_until='networkidle'); pg.wait_for_selector('#loginBtn', state='visible', timeout=20000)
                    pg.click('#loginBtn'); pg.wait_for_selector('#metrics .card', timeout=90000); pg.wait_for_timeout(800)
                    if hide: pg.evaluate("(()=>{const b=document.querySelector('[data-q=hide]');if(b&&b.getAttribute('aria-pressed')!=='true')b.click()})()"); pg.wait_for_timeout(500)
                    suffix = ' · μενού κρυμμένο' if hide else ''
                    if lay == 'none':
                        total += audit_page(pg, f'{W}x{H} · χωρίς διάταξη{suffix}', quick)
                    else:
                        if pg.evaluate(f"document.querySelector('[data-q=\"{lay}\"]').disabled"): continue
                        pg.evaluate(f"document.querySelector('[data-q=\"{lay}\"]').click()"); pg.wait_for_timeout(3000)
                        for i, fr in enumerate(pg.query_selector_all('#splitHost iframe')):
                            try: fr.content_frame().wait_for_function("!!document.getElementById('app')&&!document.getElementById('app').classList.contains('hidden')", timeout=60000)
                            except Exception: pass
                            total += audit_page(fr.content_frame(), f'{W}x{H} · διάταξη {lay} · παράθυρο {i + 1}{suffix}', quick or lay in ('c3', 'q'))
                finally:
                    ctx.close()
        finally:
            b.close()
    return total


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    print('ΠΡΟΒΛΗΜΑΤΑ ΑΠΟΘΗΚΗΣ ΣΤΑΘΕΡΩΝ ΣΗΜΕΙΩΝ:', run(args[0] if args else 'http://127.0.0.1:8000', '--quick' in sys.argv, 'layouts' if '--layouts' in sys.argv else ('none' if '--none' in sys.argv else None)))
