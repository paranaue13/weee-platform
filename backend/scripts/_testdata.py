"""Βοηθητικό για τις δοκιμές: αν στο ΑΝΤΙΓΡΑΦΟ της βάσης δεν υπάρχουν μερίδια με μέσο συλλογής (π.χ. το απόθεμα είναι όλο χύμα),
δίνει μέσα (με απόβαρο) σε μερικά μεγάλα χύμα μερίδια -- ΜΟΝΟ στο αντίγραφο δοκιμών, ποτέ στην πραγματική βάση."""
import sqlite3
def ensure_medium_lots(db, need=3, min_kg=150, type_code=None):
    c = sqlite3.connect(db)
    if type_code:   # μέσα συγκεκριμένου τύπου (π.χ. BASKET_LARGE)
        media = [r[0] for r in c.execute("select m.id from collection_media m join collection_medium_types t on t.id=m.type_id where m.active=1 and t.code=? order by m.code limit ?", (type_code, need)).fetchall()]
        lots = [r[0] for r in c.execute("select id from weee_stock_lots where collection_medium_id is null and available_weight>=? order by available_weight desc limit ?", (min_kg, need)).fetchall()]
        for m, l in zip(media, lots):
            c.execute("update weee_stock_lots set collection_medium_id=? where id=?", (m, l)); c.execute("update collection_media set status='WEEE_STORAGE' where id=?", (m,))
        c.commit(); c.close(); return
    have = c.execute("select count(*) from weee_stock_lots l join collection_media m on m.id=l.collection_medium_id where l.available_weight>=? and m.tare_weight>0", (min_kg,)).fetchone()[0]
    if have >= need: c.close(); return
    media = [r[0] for r in c.execute("select id from collection_media where active=1 and tare_weight>0 order by id limit ?", (need,)).fetchall()]
    lots = [r[0] for r in c.execute("select id from weee_stock_lots where collection_medium_id is null and available_weight>=? order by available_weight desc limit ?", (min_kg, need)).fetchall()]
    for m, l in zip(media, lots):
        c.execute("update weee_stock_lots set collection_medium_id=? where id=?", (m, l)); c.execute("update collection_media set status='WEEE_STORAGE' where id=?", (m,))
    c.commit(); c.close()
