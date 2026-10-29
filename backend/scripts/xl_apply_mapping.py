"""Αποθηκεύει μόνιμα στη βάση (μέσω του server) τις αντιστοιχίσεις ετικετών Excel → υλικά από το αρχείο του χρήστη.
Χρήση:  python xl_apply_mapping.py <base_url> [<αρχείο αντιστοιχίσεων>]     (ΠΡΩΤΑ στο αντίγραφο http://127.0.0.1:8020, μετά με backup στην πραγματική)
Ξαναεκτελείται με ασφάλεια (upsert): νέες αντιστοιχίσεις προστίθενται, οι υπάρχουσες ενημερώνονται."""
import sys, os, sqlite3, json
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from xl_mapping_file import parse, resolve, TABS
from playwright.sync_api import sync_playwright
from _browser import launch

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8020'
FILE = sys.argv[2] if len(sys.argv) > 2 else r'C:\Users\paran\Desktop\HER app\Files\antistoixisi_apotelesma.txt'
SHEET_KEY = {'Αξιοποιήσιμα Υλικά': 'AXIOPOIISIMA', 'Υλικά Ειδικής Διαχείρισης': 'EIDIKIS_DIACHEIRISIS', 'Πλακέτες': 'PLAKETES', 'Υλικά προς Απόρριψη': 'APORRIPSI', 'Πρέσα': 'PRESS', 'Εμπορικά': 'COMMERCIAL'}
PL_ORDER = ['ΠΛΑΣΤΙΚΟ ΜΑΥΡΟ', 'ΠΛΑΣΤΙΚΟ ΑΣΠΡΟ', 'ΠΛΑΣΤΙΚΟ ΑΝΑΜΕΙΚΤΟ']        # σειρά μελών της ετικέτας ΠΛΑΣΤΙΚΑ ΜΕΡΗ (όπως τη δήλωσε ο χρήστης)

rows = parse(FILE)
# για την επίλυση κωδικών χρειάζεται η ίδια βάση που εξυπηρετεί ο server: διαβάζεται μέσω API (όχι απευθείας από αρχείο)
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={'width': 1200, 'height': 800})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(BASE + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(1000)
    res = pg.evaluate("""async(rows)=>{
      const mats=await api('/master/materials?include_inactive=true');
      const u=await api('/mat/label-universe');
      const norm=s=>foldName(s);
      const byErp={};mats.forEach(m=>{(byErp[norm(m.galaxy_code||'')]=byErp[norm(m.galaxy_code||'')]||[]).push(m)});
      const weee=Object.fromEntries(u.weee.map(w=>[norm(w.code),w]));
      return {mats:mats.length,weee:u.weee.length};
    }""", rows)
    print('επικοινωνία με server:', res)
    out = pg.evaluate("""async([rows,SHEET_KEY,TABS,PL])=>{
      const mats=await api('/master/materials?include_inactive=true');
      const u=await api('/mat/label-universe');
      const N=s=>foldName(s);
      const byErp={};mats.forEach(m=>{const k=N(m.galaxy_code||'');(byErp[k]=byErp[k]||[]).push(m)});
      const weee=Object.fromEntries(u.weee.map(w=>[N(w.code),w]));
      const log=[],bad=[];
      const keep=['internal_code','internal_name','galaxy_code','galaxy_description','genre','official_description','her_description','short_description','can_bale','is_commercial','press_label','eka_code','reptool_code','reptool_description','is_precious','export_step_kg','storage_group_id','is_umbrella','label_group','label_group_order'];
      const put=async(m,patch)=>{const body={};keep.forEach(k=>{if(k in m)body[k]=m[k]});Object.assign(body,patch);await api('/master/materials/'+m.id,{method:'PUT',body:JSON.stringify(body)})};
      // 1) υλικά-ομπρέλες (00195, 00152, 00034)
      const umbErp=[...new Set(rows.filter(r=>r.kind==='BULK_SUB').map(r=>r.erp))];
      for(const erp of umbErp){const m=(byErp[N(erp)]||[])[0];if(!m){bad.push('ομπρέλα '+erp+' δεν βρέθηκε');continue}
        if(!m.is_umbrella){await put(m,{is_umbrella:true});log.push('ομπρέλα ενεργοποιήθηκε: '+erp)}}
      // 2) μέλη της ετικέτας ΠΛΑΣΤΙΚΑ ΜΕΡΗ (Πρέσα): ΜΑΥΡΟ, ΑΣΠΡΟ, ΑΝΑΜΕΙΚΤΟ
      const sums=rows.filter(r=>r.kind==='SUM');
      for(const s of sums){
        const members=PL.map(n=>mats.find(m=>N(m.official_description||m.internal_name)===N(n)&&m.can_bale&&!m.is_commercial));
        for(let i=0;i<members.length;i++){const m=members[i];if(!m){bad.push('μέλος ετικέτας '+PL[i]+' δεν βρέθηκε');continue}
          if(m.label_group!==s.group||m.label_group_order!==i){await put(m,{label_group:s.group,label_group_order:i});log.push('μέλος ετικέτας '+s.group+': '+m.galaxy_code+' · '+PL[i])}}}
      // 3) αντιστοιχίσεις
      const fresh=await api('/master/materials?include_inactive=true');const byErp2={};fresh.forEach(m=>{const k=N(m.galaxy_code||'');(byErp2[k]=byErp2[k]||[]).push(m)});
      const ord={};const items=[];
      for(const r of rows){
        const it={source:TABS[r.tab][0],label:r.label,kind:r.kind,sheet:SHEET_KEY[r.tab],active:true,sort_order:0};
        if(r.kind==='MATERIAL'||r.kind==='BULK_SUB'){const m=(byErp2[N(r.erp)]||[])[0];if(!m){bad.push(r.label+': ERP '+r.erp+' δεν βρέθηκε');continue}it.material_id=m.id}
        if(r.kind==='BULK_SUB'){ord[r.erp]=(ord[r.erp]||0);it.sort_order=ord[r.erp]++}
        if(r.kind==='RECEIPTS'){const w=weee[N(r.weee)];if(!w){bad.push(r.label+': ΑΗΗΕ '+r.weee+' δεν βρέθηκε');continue}it.weee_category_id=w.id}
        if(r.kind==='SUM')it.group_name=r.group;
        items.push(it)}
      let saved=0;
      for(let i=0;i<items.length;i+=40){const part=items.slice(i,i+40);await api('/mat/label-maps/save',{method:'POST',body:JSON.stringify({items:part})});saved+=part.length}
      return {log,bad,saved,total:rows.length};
    }""", [rows, SHEET_KEY, {k: list(v) for k, v in TABS.items()}, PL_ORDER])
    print(json.dumps(out, ensure_ascii=False, indent=1))
    eff = pg.evaluate("()=>api('/mat/label-maps/effective')")
    import collections
    print('αποθηκευμένες αντιστοιχίσεις:', len(eff['maps']), dict(collections.Counter((m['source'], m['kind']) for m in eff['maps'])))
    print('ομπρέλες:', [(u['erp'], len(u['subs'])) for u in eff['umbrellas']])
    print('ομάδες ετικετών:', [(g['name'], [m['name'] for m in g['members']]) for g in eff['groups']])
    print('JS errors:', errs)
    b.close()
