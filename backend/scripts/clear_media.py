"""Μία φορά (φάση δοκιμών): σβήνει ΟΛΑ τα μέσα συλλογής (τα στιγμιότυπα: σάκοι, παλέτες, κουτιά, καλάθια) από τη βάση.
ΔΕΝ αγγίζει τους τύπους/είδη μέσων. Οι καταχωρήσεις ταξινόμησης που τα χρησιμοποιούσαν ΜΕΝΟΥΝ και γίνονται «Χύμα»
(ίδιο καθαρό βάρος, χωρίς μέσο)· το απόβαρο/μεικτό που φαινόταν από το μέσο γράφεται στις σημειώσεις της καταχώρησης.
Χρήση:  python backend/scripts/clear_media.py [--apply] [διαδρομή βάσης]   (χωρίς --apply: μόνο αναφορά, δεν αλλάζει τίποτα)"""
import os, sqlite3, sys

sys.stdout.reconfigure(encoding="utf-8")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
apply = "--apply" in sys.argv
db = args[0] if args else os.path.expandvars(r"%LOCALAPPDATA%\WEEE Platform\data\weee_dev.db")
c = sqlite3.connect(db, timeout=60)
c.execute("pragma foreign_keys=off")

REFS = [("sorting_entries", "collection_medium_id"), ("weee_stock_lots", "collection_medium_id"),
        ("ready_material_lots", "collection_medium_id"), ("material_inventory_entries", "collection_medium_id")]
USAGE = {"IN": "εισαγωγές", "OUT": "εξαγωγές", "BOTH": "και εισαγωγές/εξαγωγές"}


def snapshot():
    loads = {}
    for lid, order, net, st in c.execute("select l.id,l.order_number,l.net_weight,l.status from inbound_loads l"):
        loads[lid] = [order, float(net or 0), st, 0.0]
    for lid, w in c.execute("select s.inbound_load_id,sum(coalesce(e.approved_weight,e.raw_weight,0)) from sorting_entries e "
                            "join sorting_sessions s on s.id=e.session_id group by s.inbound_load_id"):
        if lid in loads:
            loads[lid][3] = float(w or 0)
    return loads


print("ΒΑΣΗ:", db)
print("--- μέσα ανά είδος (πριν) ---")
total = 0
by_usage = {}
for code, name, usage, n in c.execute("select t.code,t.name_el,t.usage,count(m.id) from collection_medium_types t join collection_media m on m.type_id=t.id group by t.id order by t.usage,t.name_el"):
    print(f"  {name} [{code}] · {USAGE.get(usage, usage)}: {n}")
    total += n
    by_usage[usage] = by_usage.get(usage, 0) + n
print("  ΣΥΝΟΛΟ μέσων:", total, "· ανά χρήση:", {USAGE.get(k, k): v for k, v in by_usage.items()})
print("--- αναφορές σε μέσα (πριν) ---")
for t, col in REFS:
    print(f"  {t}.{col}:", c.execute(f"select count(*) from {t} where {col} is not null").fetchone()[0])
before = snapshot()

ents = c.execute("select e.id,e.raw_weight,e.entry_type,e.notes,ty.name_el,m.code,m.tare_weight from sorting_entries e "
                 "join collection_media m on m.id=e.collection_medium_id join collection_medium_types ty on ty.id=m.type_id").fetchall()
print("--- καταχωρήσεις ταξινόμησης που γίνονται «Χύμα»:", len(ents))
for e in ents:
    print("  ", e[4], e[5], "· καθαρό", e[1], "· απόβαρο", e[6], "· τύπος", e[2])

if not apply:
    print("(δεν έγινε καμία αλλαγή· πρόσθεσε --apply)")
    sys.exit(0)

c.execute("begin")
try:
    for eid, raw, etype, notes, tname, mcode, tare in ents:
        tare = float(tare or 0)
        note = f"Πρώην μέσο: {tname} · {mcode} · απόβαρο {tare:g} kg · μεικτό {float(raw or 0) + tare:g} kg"
        c.execute("update sorting_entries set collection_medium_id=null, entry_type='MEDIUM', notes=? where id=?",
                  ((notes + " | " if notes else "") + note, eid))
    for t, col in REFS[1:]:
        c.execute(f"update {t} set {col}=null where {col} is not null")
    c.execute("delete from collection_media")
    c.commit()
except Exception:
    c.rollback()
    raise

print("=== ΜΕΤΑ ===")
print("  μέσα που απομένουν:", c.execute("select count(*) from collection_media").fetchone()[0],
      "· είδη μέσων:", c.execute("select count(*) from collection_medium_types").fetchone()[0])
orph = 0
for t, col in REFS:
    n = c.execute(f"select count(*) from {t} where {col} is not null and {col} not in (select id from collection_media)").fetchone()[0]
    orph += n
    print(f"  ορφανές αναφορές {t}.{col}:", n)
print("  ορφανές συνολικά:", orph, "· foreign_key_check:", len(c.execute("pragma foreign_key_check").fetchall()))
after = snapshot()
bad = [(v[0], before[k][1], v[1], before[k][3], v[3]) for k, v in after.items() if k in before and (abs(before[k][3] - v[3]) > 1e-9 or abs(before[k][1] - v[1]) > 1e-9)]
print("  φορτία με διαφορά σε σύνολο παραλαβής/ταξινόμησης:", len(bad), bad[:5])
for lid, v in after.items():
    if v[0] in ("813983", "813982"):
        print("  εντολή", v[0], "· παραλαβή", before[lid][1], "→", v[1], "· ταξινόμηση", before[lid][3], "→", v[3])
