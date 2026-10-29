"""Ενημερώνει ΜΙΑ αποθηκευμένη αντιστοίχιση ετικέτας (upsert) μέσω του server.
Χρήση: python xl_set_map.py <base_url> <πηγή EXCEL|PRESS|COMMERCIAL> "<ετικέτα>" <ERP> <καρτέλα AXIOPOIISIMA|EIDIKIS_DIACHEIRISIS|PLAKETES|APORRIPSI|PRESS|COMMERCIAL>"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__)); sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from _browser import launch
base, source, label, erp, sheet = sys.argv[1:6]
with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page()
    pg.goto(base + '/', wait_until='networkidle')
    pg.wait_for_selector('#loginBtn', state='visible'); pg.click('#loginBtn')
    pg.wait_for_selector('#metrics .card', timeout=20000); pg.wait_for_timeout(800)
    r = pg.evaluate("""async([source,label,erp,sheet])=>{
      const mats=await api('/master/materials?include_inactive=true');
      const m=mats.filter(x=>foldName(x.galaxy_code||'')===foldName(erp));
      if(m.length!==1)return {error:'ο ERP '+erp+' βρέθηκε '+m.length+' φορές'};
      const before=(await api('/mat/label-maps/effective')).maps.find(x=>x.source===source&&foldName(x.label)===foldName(label));
      await api('/mat/label-maps/save',{method:'POST',body:JSON.stringify({items:[{source,label,kind:'MATERIAL',material_id:m[0].id,sheet}]})});
      const after=(await api('/mat/label-maps/effective')).maps.find(x=>x.source===source&&foldName(x.label)===foldName(label));
      return {before:before&&{material:before.material_name,sheet:before.sheet},after:after&&{material:after.material_name,erp:m[0].galaxy_code,sheet:after.sheet}};
    }""", [source, label, erp, sheet])
    print(r)
    b.close()
