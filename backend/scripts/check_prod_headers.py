"""Έλεγχος σταθερών επικεφαλίδων Παραγωγής › Παραγωγή ανά ΑΗΗΕ (Απρίλιος 2026): ανοιχτές ομάδες, «Απόκρυψη μηδενικών στηλών», οριζόντιο scroll,
ομάδες Σύνολο/HERMES/Λοιποί (με/χωρίς κίτρινη ειδοποίηση αρνητικών), ζουμ 70/100/120. Ελέγχει: η «Ημερομηνία» και το «Σύνολο (kg)» δεν καλύπτονται,
καμία κεφαλίδα δεν είναι μετατοπισμένη από τη στήλη δεδομένων της, δεν υπάρχει κενό ανάμεσα Ημερομηνία/Σύνολο. Μόνο ανάγνωση.
Χρήση: python check_prod_headers.py [http://127.0.0.1:8000]  (WEEE_MENUPOS=left|top|bottom)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('WEEE_SCROLLBARS', '1')
from playwright.sync_api import sync_playwright
from _browser import launch
sys.stdout.reconfigure(encoding='utf-8')
JS="""()=>{const w=document.querySelector('#productionWeeePanel .prodTableWrap');if(!w)return {err:'nowrap'};const t=w.querySelector('table');const bad=[];
const wr=w.getBoundingClientRect();
const vis=c=>{const r=c.getBoundingClientRect();if(r.width<2||r.right<wr.left+1||r.left>wr.right-1)return null;return r};
// 1) πρώτες κεφαλίδες (Ημερομηνία, Σύνολο) δεν καλύπτονται
const h0=[...t.tHead.rows[0].cells].slice(0,2);
h0.forEach((c,i)=>{const r=c.getBoundingClientRect();const e=document.elementFromPoint(Math.min(r.left+r.width/2,wr.right-20),r.top+Math.min(r.height/2,20));if(!c.contains(e))bad.push('κεφαλίδα '+(i?'Σύνολο':'Ημερομηνία')+' καλύπτεται από '+(e?(e.tagName+'.'+String(e.className).slice(0,30)+' «'+(e.innerText||'').slice(0,18)+'»'):'τίποτα')+' (scrollLeft '+Math.round(w.scrollLeft)+')')});
// 2) ευθυγράμμιση φύλλων κεφαλίδας με στήλες δεδομένων (πρώτη γραμμή σώματος)
const row=t.tBodies[0].rows[0];if(row&&!row.querySelector('.prodEmpty')){const ths=[...t.tHead.querySelectorAll('th')].map(th=>th.getBoundingClientRect());const tds=[...row.cells].slice(2);let miss=0,first=-1;tds.forEach((td,i)=>{const b=td.getBoundingClientRect();if(!ths.some(a=>Math.abs(a.left-b.left)<1.5&&Math.abs(a.width-b.width)<1.5)){miss++;if(first<0)first=i}});if(miss)bad.push('στήλες σώματος χωρίς ευθυγραμμισμένη κεφαλίδα: '+miss+' (πρώτη η '+first+')')}
// 3) κεφαλίδες ΟΜΑΔΑΣ δεν πέφτουν πάνω στην Ημερομηνία/Σύνολο (διαφανές/καλυμμένο)
const dRect=h0[0].getBoundingClientRect();const sRect=h0[1].getBoundingClientRect();
[...t.tHead.querySelectorAll('th')].slice(2).forEach(th=>{const r=th.getBoundingClientRect();const cs=getComputedStyle(th);if(r.width>2&&r.left<sRect.right-1&&r.right>dRect.left+1&&r.top<dRect.bottom-1){const e=document.elementFromPoint(Math.max(dRect.left+5,r.left+3),dRect.top+8);}});
// 4) ύψος γραμμών κεφαλίδας συνεχόμενο (κενό ανάμεσα Ημερομηνία/Σύνολο)
const gap=sRect.left-dRect.right;if(Math.abs(gap)>1.5)bad.push('κενό/επικάλυψη μεταξύ Ημερομηνίας και Συνόλου '+Math.round(gap));
const fillHole=[...t.tHead.rows[0].cells].slice(1,3);
return {bad,sl:Math.round(w.scrollLeft),sw:w.scrollWidth,cw:w.clientWidth,alert:!!document.querySelector('.negBar,#negBar,.negAlert')}}"""


def run(base='http://127.0.0.1:8000', zs=(70, 100, 120)):
    total = 0
    with sync_playwright() as p:
        b = launch(p)
        try:
            pg = b.new_context(viewport={'width': 1500, 'height': 800}).new_page(); pg.goto(base + '/', wait_until='domcontentloaded'); pg.click('#loginBtn'); pg.wait_for_selector('#app:not(.hidden)'); pg.wait_for_timeout(1500)
            pg.evaluate("show('production')"); pg.wait_for_timeout(2500)
            for _ in range(14):
                if 'Απρίλιος 2026' in pg.inner_text('#prodPeriodTitle'): break
                pg.click('#prodPrev'); pg.wait_for_timeout(500)
            for z in zs:
                pg.evaluate(f"setViewZoom({z})"); pg.wait_for_timeout(700)
                for grp in ('ALL', 'HERMES', 'OTHER'):
                    pg.click(f'[data-prodgroup="{grp}"]'); pg.wait_for_timeout(500)
                    for stock in (False, True):
                        pg.evaluate(f"(()=>{{const c=document.getElementById('prodStockOnly');if(c&&c.checked!=={str(stock).lower()}){{c.checked={str(stock).lower()};c.dispatchEvent(new Event('change',{{bubbles:true}}))}}}})()"); pg.wait_for_timeout(500)
                        for exp in (False, True):
                            pg.evaluate("(x)=>{document.querySelectorAll('.prodMajorHead[data-prodcat]').forEach(h=>{const on=h.classList.contains('expanded');if(on!==x)h.click()})}", exp); pg.wait_for_timeout(700)
                            for sx in ('0', 'mid', 'max'):
                                pg.evaluate("(sx)=>{const w=document.querySelector('#productionWeeePanel .prodTableWrap');if(w)w.scrollLeft=sx==='0'?0:sx==='mid'?w.scrollWidth/2:1e9}", sx); pg.wait_for_timeout(250)
                                r = pg.evaluate(JS)
                                if r.get('err') or r['bad']:
                                    total += 1; print(f'[z{z} {grp} μηδενικά κρυμμένα={stock} ανοιχτές ομάδες={exp} scroll={sx}]', r.get('err') or r['bad'])
        finally:
            b.close()
    return total


if __name__ == '__main__':
    print('ΠΡΟΒΛΗΜΑΤΑ ΕΠΙΚΕΦΑΛΙΔΩΝ ΠΑΡΑΓΩΓΗΣ:', run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'))
