r"""Συγχώνευση των μέσων Χύμα «BULK-…» στο Χύμα χωρίς μέσο (μία εγγραφή Χύμα, χωρίς αριθμό/αποβαρό).

  Έλεγχος (χωρίς αλλαγές):  backend\.venv\Scripts\python.exe backend\scripts\merge_bulk_medium.py
  Εφαρμογή:                 backend\.venv\Scripts\python.exe backend\scripts\merge_bulk_medium.py --apply

Για κάθε μέσο τύπου BULK: οι καταχωρήσεις ταξινόμησης και οι παρτίδες αποθήκης περνούν σε «χωρίς μέσο» (entry_type BULK),
το μέσο γίνεται ανενεργό (δεν σβήνεται) και γράφεται σημείωση στο ιστορικό αλλαγών. Κάνε πρώτα αντίγραφο της βάσης."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select, func
from app.db import SessionLocal
from app import models as M
from app.audit import write_audit

APPLY = '--apply' in sys.argv
with SessionLocal() as db:
    bt = db.scalar(select(M.CollectionMediumType).where(M.CollectionMediumType.code == 'BULK'))
    media = db.scalars(select(M.CollectionMedium).where(M.CollectionMedium.type_id == bt.id)).all() if bt else []
    def kg(): return float(db.scalar(select(func.coalesce(func.sum(M.WEEEStockLot.available_weight), 0)).where(M.WEEEStockLot.available_weight > 0)) or 0)
    print('Μέσα Χύμα (BULK-…):', [m.code for m in media], '| ενεργά:', [m.code for m in media if m.active])
    tot_before = kg(); print('Συνολικό διαθέσιμο απόθεμα ΑΗΗΕ πριν: %.3f kg' % tot_before)
    n_e = n_l = 0
    for m in media:
        ents = db.scalars(select(M.SortingEntry).where(M.SortingEntry.collection_medium_id == m.id)).all()
        lots = db.scalars(select(M.WEEEStockLot).where(M.WEEEStockLot.collection_medium_id == m.id)).all()
        print(f' {m.code}: {len(ents)} καταχωρήσεις, {len(lots)} παρτίδες ({sum(float(l.available_weight or 0) for l in lots):g} kg διαθέσιμα)')
        if not APPLY: continue
        for e in ents: e.collection_medium_id = None; e.entry_type = 'BULK'; n_e += 1
        for l in lots: l.collection_medium_id = None; n_l += 1
        old = {'active': m.active}; m.active = False
        write_audit(db, None, 'collection_medium', m.id, 'MERGE_INTO_BULK', old=old, new={'active': False, 'entries': len(ents), 'lots': len(lots)},
                    reason='Συγχώνευση στο Χύμα χωρίς μέσο (μία εγγραφή Χύμα, χωρίς αριθμό/αποβαρό)')
    if not APPLY:
        print('\n(έλεγχος μόνο — τίποτα δεν άλλαξε. Πρόσθεσε --apply για εφαρμογή)'); sys.exit(0)
    db.commit()
    print(f'Έγινε: {n_e} καταχωρήσεις, {n_l} παρτίδες -> Χύμα χωρίς μέσο. Σύνολο μετά: %.3f kg' % kg())
