"""Έλεγχος εμφάνισης/πλάτους των πινάκων της Αποθήκης ΑΗΗΕ με ΟΡΑΤΕΣ μπάρες scroll (όπως στον πραγματικό Chrome: οι μπάρες παίρνουν πλάτος).
Σε πολλά μεγέθη παραθύρου, καρτέλες Αποθήκη / Μέσα συλλογής / ΜΗ ΑΗΗΕ, και scroll οριζόντια (αρχή, τέλος) και κάθετα (αρχή, μέση, τέλος):
 (1) οι δύο πίνακες Αποθήκης έχουν ίδιο πλάτος και ίδια άκρα,
 (2) ο πίνακας γεμίζει το πλαίσιο· αν οι στήλες δεν χωράνε, στο τέρμα του scroll το δεξί άκρο του πίνακα ταιριάζει με το δεξί άκρο του πλαισίου (χωρίς κενό και χωρίς περιττή διαδρομή),
 (3) το φόντο κάθε γραμμής είναι συμπαγές και ίδιο σε ΟΛΟ το πλάτος (πραγματικά pixel): πρώτες στήλες = υπόλοιπη γραμμή, κεφαλίδα ομοιόμορφη,
 (4) η γραμμή κάτω από την κολλητή κεφαλίδα φαίνεται ΠΑΝΤΑ (και με scroll κάτω),
 (5) τα κουμπιά πάνω δεξιά και οι κάρτες δεν κόβονται στο δεξί άκρο,
 (6) οι στήλες «Προς επεξεργασία» / «Προς αποστολή» δεν φαίνονται.
Μόνο ανάγνωση. Χρήση: python check_weee_paint.py [http://127.0.0.1:8000]"""
import io, os, sys
os.environ["WEEE_SCROLLBARS"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image
from playwright.sync_api import sync_playwright
from _browser import launch

SIZES = [(1920, 1080), (1536, 730), (1366, 768), (1280, 720), (1100, 700)]
TABS = ["stock", "media", "nonweee"]

GEOM = """()=>{const v=document.getElementById('weee');const R=e=>{const b=e.getBoundingClientRect();return {l:b.left,r:b.right,t:b.top,b:b.bottom,w:b.width}};
 const vr=R(v),cr=vr.r-(v.offsetWidth-v.clientWidth);
 const tabs=[...v.querySelectorAll('.stockTable')].filter(t=>t.offsetParent);
 const o={view:vr,clientR:cr,sw:v.scrollWidth,cw:v.clientWidth,sx:v.scrollLeft,sy:v.scrollTop,maxY:v.scrollHeight-v.clientHeight,tables:tabs.map(t=>({id:t.id,rect:R(t),
   hdr:[...t.tHead.rows[0].cells].filter(c=>getComputedStyle(c).display!=='none').map(c=>{const b=c.getBoundingClientRect();const cs=getComputedStyle(c);return {txt:c.innerText.trim().slice(0,16),l:b.left,r:b.right,t:b.top,b:b.bottom,bg:cs.backgroundColor,bgi:cs.backgroundImage,pos:cs.position,wcol:c.dataset.wcol||''}}),
   rows:[...t.tBodies[0].rows].slice(0,12).map(r=>{const rr=r.getBoundingClientRect(),rs=getComputedStyle(r);return {cls:r.className,t:rr.top,b:rr.bottom,bg:rs.backgroundColor,cells:[...r.cells].filter(c=>getComputedStyle(c).display!=='none').map(c=>{const cs=getComputedStyle(c);return {l:c.getBoundingClientRect().left,r:c.getBoundingClientRect().right,bg:cs.backgroundColor,bgi:cs.backgroundImage,pos:cs.position}})}})}))};
 const btns=[...document.querySelectorAll('#weeeStick .weeeRight .btn, #weeeStick .weeeKpisCompact>*:last-child')].filter(e=>e.offsetParent).map(e=>({n:(e.id||e.className).toString().slice(0,24),r:e.getBoundingClientRect().right}));
 o.edge=btns;return o}"""


def rgb(s):
    if not s or s.startswith("rgba(0, 0, 0, 0)") or s == "transparent":
        return None
    import re
    m = re.findall(r"[\d.]+", s)
    return tuple(round(float(x)) for x in m[:3]) if len(m) >= 3 else None


def close(a, b, tol=3):
    return a is not None and b is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


def run(base="http://127.0.0.1:8000", quick=False):
    total = 0

    def bad(msg):
        nonlocal total
        total += 1
        print(msg)
    with sync_playwright() as p:
        b = launch(p)
        try:
            for (W, H) in (SIZES[:2] if quick else SIZES):
                pg = b.new_context(viewport={"width": W, "height": H}).new_page()
                pg.goto(base + "/", wait_until="load", timeout=90000); pg.click("#loginBtn"); pg.wait_for_selector("#metrics .card", timeout=90000); pg.wait_for_timeout(700)
                pg.evaluate("show('weee')"); pg.mouse.move(2, 2); pg.wait_for_timeout(2800)
                for tab in TABS:
                    pg.evaluate(f"document.querySelector('[data-weeetab=\"{tab}\"]').click()"); pg.mouse.move(2, 2); pg.wait_for_timeout(1800)
                    T = f"[{W}x{H} · {tab}]"
                    for sx in ("0", "max"):
                        pg.evaluate(f"(()=>{{const v=document.getElementById('weee');v.scrollLeft={'0' if sx=='0' else '1e9'};v.scrollTop=0}})()"); pg.wait_for_timeout(250)
                        g = pg.evaluate(GEOM)
                        cr = g["clientR"]
                        tbs = g["tables"]
                        if tab == "stock" and len(tbs) == 2:
                            a, c = tbs[0]["rect"], tbs[1]["rect"]
                            if abs(a["w"] - c["w"]) > 0.6 or abs(a["l"] - c["l"]) > 0.6:
                                bad(f"{T} οι δύο πίνακες δεν έχουν ίδιο πλάτος ({a['w']:.1f} / {c['w']:.1f})")
                            for t in tbs:
                                if any(h["wcol"] == "todo" for h in t["hdr"]):
                                    bad(f"{T} φαίνεται ακόμα η στήλη «Προς επεξεργασία/αποστολή» στον {t['id']}")
                        over = g["sw"] - g["cw"]
                        for t in tbs:
                            r = t["rect"]
                            if sx == "0" and r["w"] < g["cw"] - 2.5:
                                bad(f"{T} ο {t['id']} δεν γεμίζει το πλαίσιο ({r['w']:.1f} < {g['cw']})")
                            if over > 2 and sx == "max":
                                if abs(r["r"] - cr) > 1.5:
                                    bad(f"{T} στο τέρμα scroll ο {t['id']} δεν τελειώνει στο δεξί άκρο του πλαισίου (πίνακας {r['r']:.1f}, πλαίσιο {cr:.1f})")
                        if over > 2 and sx == "max" and abs(g["sx"] - over) > 1.5:
                            bad(f"{T} το οριζόντιο scroll δεν φτάνει στο τέλος ({g['sx']:.1f} από {over})")
                        if over <= 2 and sx == "0":
                            pass
                        # (5) δεξιά άκρα
                        if sx == "0":
                            for e in g["edge"]:
                                if e["r"] > cr + 0.6:
                                    bad(f"{T} το «{e['n']}» κόβεται/κολλά στο δεξί άκρο ({e['r']:.1f} > {cr + 0.6:.1f})")
                        # (3) χρώματα με στοιχεία DOM
                        for t in tbs:
                            hb = [rgb(h["bg"]) for h in t["hdr"]]
                            if len(set(hb)) > 1 or None in hb:
                                bad(f"{T} {t['id']}: η κεφαλίδα δεν έχει ομοιόμορφο συμπαγές φόντο {set(hb)}")
                            for h in t["hdr"][:2]:
                                if h["bgi"] != "none":
                                    bad(f"{T} {t['id']}: κλίση στο φόντο κολλητής κεφαλίδας")
                            for ri, row in enumerate(t["rows"]):
                                cells = row["cells"]
                                if len(cells) < 3:
                                    continue
                                trbg = rgb(row["bg"])
                                other = [rgb(c["bg"]) or trbg for c in cells[2:]]
                                st = [rgb(c["bg"]) for c in cells[:2]]
                                if any(c["bgi"] != "none" for c in cells[:2]):
                                    bad(f"{T} {t['id']} γραμμή {ri}: κολλητή περιοχή με κλίση αντί για συμπαγές χρώμα")
                                if None in other or any(o is None for o in other):
                                    bad(f"{T} {t['id']} γραμμή {ri} ({row['cls']}): δεν έχει φόντο σε όλο το πλάτος")
                                elif not all(close(st[i], other[0], 2) for i in range(2)) or len(set(other)) > 1:
                                    bad(f"{T} {t['id']} γραμμή {ri} ({row['cls']}): η κολλητή περιοχή {st} έχει άλλο χρώμα από τα δεδομένα {set(other)}")
                        # (3) pixel: ίδιο χρώμα σε όλο το πλάτος (πάνω γραμμή κάθε γραμμής, χωρίς κείμενο)
                        img = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
                        for t in tbs:
                            for name, y0, exp in [("κεφαλίδα", t["hdr"][0]["t"] + 3, rgb(t["hdr"][0]["bg"]))] + [(f"γραμμή {i}", r["t"] + 2, None) for i, r in enumerate(t["rows"][:6]) if r["t"] > g["view"]["t"] + 30 and r["b"] < g["view"]["t"] + g["cw"] * 3]:
                                y = int(y0)
                                if y < 0 or y >= H - 20:
                                    continue
                                xs = [int(x) for x in range(int(max(g["view"]["l"] + 3, t["rect"]["l"] + 3)), int(min(cr - 3, t["rect"]["r"] - 3)), 7)]
                                cols = [img.getpixel((x, y))[:3] for x in xs]
                                ref = exp or cols[0]
                                flags = [not close(c, ref, 4) for c in cols]
                                off = [(x, c) for i, (x, c) in enumerate(zip(xs, cols)) if flags[i] and not (max(c) - min(c) <= 3 and sum(c) < 450) and (i + 1 < len(flags) and flags[i + 1] or i > 0 and flags[i - 1])]   # μεμονωμένο pixel (π.χ. λαβή στήλης) δεν μετράει
                                if off:
                                    bad(f"{T} {t['id']} {name}: το χρώμα αλλάζει σε x={off[0][0]} ({off[0][1]} αντί {ref})")
                    # (4) γραμμή κεφαλίδας με scroll κάτω
                    if tab == "stock":
                        for sy in ("mid", "max"):
                            pg.evaluate(f"(()=>{{const v=document.getElementById('weee');v.scrollLeft=0;v.scrollTop={'Math.round((v.scrollHeight-v.clientHeight)/2)' if sy=='mid' else 'v.scrollHeight'}}})()"); pg.wait_for_timeout(300)
                            g = pg.evaluate(GEOM)
                            img = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
                            pinned = max((t["hdr"][0]["t"] for t in g["tables"]), default=0)
                            for t in g["tables"]:
                                h0 = t["hdr"][0]
                                if h0["t"] < pinned - 2:
                                    continue   # η κεφαλίδα φεύγει φυσιολογικά μαζί με το τέλος του πίνακά της (δεν είναι καρφωμένη)
                                if h0["pos"] != "sticky" or not (g["view"]["t"] < h0["t"] < g["view"]["t"] + 400) or h0["b"] > H - 40:
                                    continue
                                y = int(h0["b"]) - 1
                                lv = [min((img.getpixel((x, yy))[:3] for yy in (y, y + 1)), key=sum) for x in range(int(h0["l"]) + 5, int(min(g["clientR"] - 5, t["hdr"][-1]["r"] - 5)), 40)]   # η γραμμή πέφτει στο pixel round(κάτω άκρο)
                                dark = sum(1 for c in lv if sum(c) < 3 * 215)
                                if dark < len(lv) * 0.9:
                                    bad(f"{T} {t['id']} scroll κάτω ({sy}): η γραμμή κάτω από την κολλητή κεφαλίδα δεν φαίνεται παντού ({dark}/{len(lv)})")
                pg.context.close()
        finally:
            b.close()
    return total


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://127.0.0.1:8000"
    print("ΠΡΟΒΛΗΜΑΤΑ ΕΜΦΑΝΙΣΗΣ ΑΠΟΘΗΚΗΣ ΑΗΗΕ:", run(base, "γρήγορο" in sys.argv))
