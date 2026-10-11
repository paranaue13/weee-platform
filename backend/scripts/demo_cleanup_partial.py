"""Μερικός καθαρισμός DEMO: σβήνει ό,τι είναι DEMO και ΔΕΝ είναι δεμένο σε επιβεβαιωμένη παραγωγή.

  Έλεγχος (χωρίς αλλαγές):  backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_cleanup_partial.py
  Εφαρμογή:                 backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_cleanup_partial.py --apply

Τι ΜΕΝΕΙ: τα kg DEMO που έχουν περάσει σε ΕΠΙΒΕΒΑΙΩΜΕΝΗ μεταφορά παραγωγής (και ό,τι χρειάζονται: μέσο, καταχώρηση ταξινόμησης,
παραλαβή/ταξινόμηση DEMO). Ό,τι δεν είναι DEMO δεν αγγίζεται ποτέ."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select, delete as sa_delete, func
from app.db import SessionLocal
from app import models as M

APPLY = '--apply' in sys.argv
counts = {}
def note(name, n): counts[name] = counts.get(name, 0) + (n or 0)

with SessionLocal() as db:
    trip = db.scalar(select(M.InboundTrip).where(M.InboundTrip.receipt_number == 'DEMO-0001'))
    demo_entry_ids, demo_lot_ids = [], []
    if trip:
        load_ids = [l.id for l in db.scalars(select(M.InboundLoad).where(M.InboundLoad.trip_id == trip.id)).all()]
        sess_ids = [s.id for s in db.scalars(select(M.SortingSession).where(M.SortingSession.inbound_load_id.in_(load_ids))).all()] if load_ids else []
        demo_entry_ids = [e.id for e in db.scalars(select(M.SortingEntry).where(M.SortingEntry.session_id.in_(sess_ids))).all()] if sess_ids else []
        demo_lot_ids = [l.id for l in db.scalars(select(M.WEEEStockLot).where(M.WEEEStockLot.source_sorting_entry_id.in_(demo_entry_ids))).all()] if demo_entry_ids else []
    # μεταφορές που αγγίζουν DEMO lots
    items = db.scalars(select(M.ProductionTransferItem).where(M.ProductionTransferItem.stock_lot_id.in_(demo_lot_ids))).all() if demo_lot_ids else []
    tr_ids = {i.transfer_id for i in items}
    trs = {t.id: t for t in db.scalars(select(M.ProductionTransfer).where(M.ProductionTransfer.id.in_(tr_ids))).all()} if tr_ids else {}
    # ασφάλεια: μεταφορά με μη-DEMO lot μέσα -> δεν αγγίζεται
    mixed = set()
    if tr_ids:
        for it in db.scalars(select(M.ProductionTransferItem).where(M.ProductionTransferItem.transfer_id.in_(tr_ids))).all():
            if it.stock_lot_id not in demo_lot_ids: mixed.add(it.transfer_id)
    keep_tr = {t for t, o in trs.items() if o.status != 'CANCELLED' or t in mixed}
    del_tr = [t for t in trs if t not in keep_tr]
    keep_lots = {i.stock_lot_id for i in items if i.transfer_id in keep_tr}
    del_lots = [l for l in demo_lot_ids if l not in keep_lots]
    keep_entries = {l.source_sorting_entry_id for l in db.scalars(select(M.WEEEStockLot).where(M.WEEEStockLot.id.in_(keep_lots))).all()} if keep_lots else set()
    del_entries = [e for e in demo_entry_ids if e not in keep_entries]
    print(f'DEMO lots: {len(demo_lot_ids)} | μένουν (σε επιβεβαιωμένη παραγωγή): {len(keep_lots)} | διαγράφονται: {len(del_lots)}')
    print(f'Μεταφορές που αγγίζουν DEMO: {len(trs)} | ακυρωμένες προς διαγραφή: {len(del_tr)} | μένουν: {len(keep_tr)}')

    # 1) ΥΛΙΚΑ DEMO (Android → Υλικά)
    mlots = [l.id for l in db.scalars(select(M.ReadyMaterialLot).where(M.ReadyMaterialLot.is_demo == True)).all()]
    # μέσα που ΘΑ διαγραφούν: DEMO-* που δεν αναφέρονται από ό,τι μένει
    keep_media = set()
    for l in db.scalars(select(M.WEEEStockLot).where(M.WEEEStockLot.id.in_(keep_lots))).all():
        if l.collection_medium_id: keep_media.add(l.collection_medium_id)
    for e in db.scalars(select(M.SortingEntry).where(M.SortingEntry.id.in_(keep_entries))).all():
        if e.collection_medium_id: keep_media.add(e.collection_medium_id)
    demo_media = db.scalars(select(M.CollectionMedium).where(M.CollectionMedium.code.like('DEMO%'))).all()
    del_media = []
    for m in demo_media:
        if m.id in keep_media: continue
        # καμία αναφορά από μη-DEMO δεδομένα
        refs = 0
        refs += db.scalar(select(func.count()).select_from(M.SortingEntry).where(M.SortingEntry.collection_medium_id == m.id, M.SortingEntry.id.notin_(del_entries))) or 0
        refs += db.scalar(select(func.count()).select_from(M.WEEEStockLot).where(M.WEEEStockLot.collection_medium_id == m.id, M.WEEEStockLot.id.notin_(del_lots))) or 0
        refs += db.scalar(select(func.count()).select_from(M.ReadyMaterialLot).where(M.ReadyMaterialLot.collection_medium_id == m.id, M.ReadyMaterialLot.id.notin_(mlots))) or 0
        refs += db.scalar(select(func.count()).select_from(M.MaterialInventoryEntry).where(M.MaterialInventoryEntry.collection_medium_id == m.id, M.MaterialInventoryEntry.is_demo == False)) or 0
        if refs: print('ΜΕΝΕΙ (δεμένο σε μη-DEMO):', m.code, refs); continue
        del_media.append(m)
    print(f'DEMO μέσα: {len(demo_media)} | μένουν: {len(demo_media)-len(del_media)} | διαγράφονται: {len(del_media)}')

    if not APPLY:
        print('\n(έλεγχος μόνο — τίποτα δεν σβήστηκε. Πρόσθεσε --apply για εφαρμογή)'); sys.exit(0)

    def cnt(res): return res.rowcount or 0
    # Υλικά
    if mlots:
        note('ready_material_movements', cnt(db.execute(sa_delete(M.ReadyMaterialMovement).where(M.ReadyMaterialMovement.lot_id.in_(mlots)))))
        note('loading_reservations', cnt(db.execute(sa_delete(M.LoadingReservation).where(M.LoadingReservation.ready_material_lot_id.in_(mlots)))))
        note('ready_material_lots', cnt(db.execute(sa_delete(M.ReadyMaterialLot).where(M.ReadyMaterialLot.id.in_(mlots)))))
    note('material_inventory_entries', cnt(db.execute(sa_delete(M.MaterialInventoryEntry).where(M.MaterialInventoryEntry.is_demo == True))))
    note('app_settings(matmedium.seq.DEMO)', cnt(db.execute(sa_delete(M.AppSetting).where(M.AppSetting.key.like('matmedium.seq.DEMO-%')))))
    # Ακυρωμένες μεταφορές DEMO και ό,τι εξαρτάται
    if del_tr:
        item_ids = [i.id for i in db.scalars(select(M.ProductionTransferItem).where(M.ProductionTransferItem.transfer_id.in_(del_tr))).all()]
        if item_ids: note('production_input_balances', cnt(db.execute(sa_delete(M.ProductionInputBalance).where(M.ProductionInputBalance.transfer_item_id.in_(item_ids)))))
        note('production_work_entries', cnt(db.execute(sa_delete(M.ProductionWorkEntry).where(M.ProductionWorkEntry.transfer_id.in_(del_tr)))))
        note('production_transfer_items', cnt(db.execute(sa_delete(M.ProductionTransferItem).where(M.ProductionTransferItem.transfer_id.in_(del_tr)))))
        note('production_transfers', cnt(db.execute(sa_delete(M.ProductionTransfer).where(M.ProductionTransfer.id.in_(del_tr)))))
    # Απόθεμα ΑΗΗΕ DEMO + καταχωρήσεις ταξινόμησης
    if del_lots:
        note('stock_movements', cnt(db.execute(sa_delete(M.StockMovement).where(M.StockMovement.lot_id.in_(del_lots)))))
        note('weee_stock_lots', cnt(db.execute(sa_delete(M.WEEEStockLot).where(M.WEEEStockLot.id.in_(del_lots)))))
    if del_entries:
        note('sorting_adjustments', cnt(db.execute(sa_delete(M.SortingAdjustment).where(M.SortingAdjustment.sorting_entry_id.in_(del_entries)))))
        note('sorting_entries', cnt(db.execute(sa_delete(M.SortingEntry).where(M.SortingEntry.id.in_(del_entries)))))
    db.flush()
    for m in del_media:
        db.delete(m); note('collection_media', 1)
    db.commit()
    print('\nΣΒΗΣΤΗΚΑΝ:')
    for k, v in counts.items(): print(f'  {k}: {v}')
