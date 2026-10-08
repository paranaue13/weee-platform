"""DEMO δεδομένα για το Android (εικονικά κιλά σε καλάθια / παλέτες / σάκους / χύμα).

  Δημιουργία :  backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_data.py create
  Σβήσιμο    :  backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_data.py delete
  Μόνο ΥΛΙΚΑ DEMO :  backend\.venv\Scripts\python.exe backend\scripts\demo_data.py delete-materials
  Κατάσταση  :  backend\\.venv\\Scripts\\python.exe backend\\scripts\\demo_data.py status

Ετικέτα DEMO: μία παραλαβή «DEMO-0001» (εντολή «DEMO», σημείωση «DEMO») με ταξινόμηση ΚΛΕΙΣΤΗ· όλα τα εικονικά
κιλά είναι μερίδια αποθέματος αυτής της ταξινόμησης (ίδιος τρόπος με την Ταξινόμηση). Τα νέα μέσα (Infocycle 1,
παλέτες, σάκοι) έχουν κωδικό που αρχίζει από «DEMO-». Το σβήσιμο αφαιρεί ΜΟΝΟ αυτά και ξαναγυρίζει τα υπάρχοντα
καλάθια του Μητρώου σε «διαθέσιμο». Δεν αλλάζει δομή βάσης ούτε αγγίζει πραγματικές εγγραφές.
Αν έχεις ήδη περάσει DEMO κιλά στην Παραγωγή, το σβήσιμο σταματά και ζητά  delete --and-transfers.
"""
import sys, os
from datetime import datetime, timezone
from decimal import Decimal
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select, delete as sa_delete, func
from app.db import SessionLocal
from app import models
from app.models import (User, Organization, InboundTrip, InboundLoad, SortingSession, SortingEntry, WEEEStockLot, StockMovement,
    CollectionMedium, CollectionMediumType, WEEECategory, ProductionTransfer, ProductionTransferItem, ProductionInputBalance,
    ProductionWorkEntry)
from app import main as appmain

TAG = 'DEMO'
RECEIPT = 'DEMO-0001'
N_BASKET = 8      # ανά τύπο καλαθιού
N_PALLET = 6
PALLET_TARES = [22, 25, 28, 30, 26, 24]
N_SACK1, N_SACK2 = 4, 4
BULK = [('4Α2110', 140), ('4Α1000', 95)]
# Βάρος ανά είδος: βαριά / μεσαία / ελαφριά (0..1) -> ρεαλιστικά κιλά ανά τύπο υλικού
HEAVY = ('Κλιματιστικά', 'Πλυντήρια', 'Κουζίνες', 'Θερμοσίφωνες', 'ψύξη', 'Αφυγραντήρες', 'Τηλεοράσεις', 'Οθόνες', 'Αυτόματοι Διανομείς',
         'PC - Server', 'Φωτοτυπικά', 'έλαια', 'ρευστά', 'Σκούπες - Σίδερα')
LIGHT = ('Laptops', 'Tablets', 'Κινητά', 'Φωτιστικά', 'Παιχνίδ', 'Ιατρικά', 'Ανιχνευτές', 'Ταμειακές', 'Πληκτρολόγια', 'Modem', 'Εκτυπωτές',
         'Scanner', 'Projectors', 'UPS', 'Καλώδια', 'Ηχεία')
GROUP_PICK = {'1': 4, '2': 7, '4': 12, '5': 7, '6': 8}   # πόσες διαφορετικές κατηγορίες από κάθε ομάδα


def weight_class(desc, i):
    jit = ((i * 37) % 11) / 100.0
    if any(k.lower() in desc.lower() for k in HEAVY): return 0.78 + jit
    if any(k.lower() in desc.lower() for k in LIGHT): return 0.04 + jit * 1.5
    return 0.38 + jit


def pick_categories(db):
    """Διαφορετικές κατηγορίες ΑΗΗΕ από ΟΛΕΣ τις ομάδες (1,2,4,5,6), υπάρχοντα ονόματα/κωδικοί, interleaved ώστε οι γειτονικές να διαφέρουν."""
    rows = db.scalars(select(WEEECategory).where(WEEECategory.active == True, WEEECategory.processable == True).order_by(WEEECategory.code)).all()
    groups = {}
    for c in rows:
        code = c.code or ''
        if len(code) == 6 and code.isdigit(): continue
        g = code[0] if code[:1].isdigit() else (code.split('-')[1][0] if code.startswith('INT-') else None)
        if g in GROUP_PICK: groups.setdefault(g, []).append(c)
    chosen = {}
    for g, n in GROUP_PICK.items():
        lst = groups.get(g, [])
        step = max(1, len(lst) // n)
        chosen[g] = (lst[::step])[:n]
    order, i = [], 0
    while any(chosen.values()):
        for g in sorted(chosen):
            if chosen[g]: order.append(chosen[g].pop(0))
    return order


def demo_trip(db):
    return db.scalar(select(InboundTrip).where(InboundTrip.receipt_number == RECEIPT))


def create(db):
    if demo_trip(db):
        print('Υπάρχουν ήδη DEMO δεδομένα. Τρέξε πρώτα:  demo_data.py delete'); return
    user = db.scalar(select(User).where(User.username == 'admin')) or db.scalar(select(User))
    sup = db.scalar(select(InboundLoad.supplier_id).limit(1)) or db.scalar(select(Organization.id).limit(1))
    types = {t.code: t for t in db.scalars(select(CollectionMediumType)).all()}
    cats = {c.code: c for c in db.scalars(select(WEEECategory)).all()}
    now = datetime.now(timezone.utc)
    cat_list = pick_categories(db)
    plan = []  # (medium, category, net_kg, entry_type)
    ci = 0
    def kg_for(cat, lo, hi, n):
        f = min(1.0, weight_class(cat.her_description or cat.description_el or '', n))
        return int(round(lo + f * (hi - lo)))
    def add(m, lo, hi):
        nonlocal ci
        cat = cat_list[ci % len(cat_list)]
        plan.append((m, cat, kg_for(cat, lo, hi, ci), 'MEDIUM')); ci += 1
    for code in ['BASKET_LARGE', 'BASKET_SMALL', 'INFOCYCLE_1', 'INFOCYCLE_2']:
        t = types[code]
        if code == 'INFOCYCLE_1':
            media = []
            for n in range(1, N_BASKET + 1):
                m = CollectionMedium(type_id=t.id, code=f'DEMO-IC1-{n}', tare_weight=None, status='AVAILABLE', active=True)
                db.add(m); media.append(m)
            db.flush()
        else:
            ms = db.scalars(select(CollectionMedium).where(CollectionMedium.type_id == t.id, CollectionMedium.status == 'AVAILABLE', CollectionMedium.active == True)).all()
            ms.sort(key=lambda m: (len(m.code), m.code))
            media = ms[-N_BASKET:]  # τα τελευταία (λιγότερο πιθανό να χρησιμοποιούνται)
        for m in media: add(m, 20, 180)
    for n, tare in enumerate(PALLET_TARES[:N_PALLET], 1):
        m = CollectionMedium(type_id=types['PALLET'].id, code=f'DEMO-P{n}', tare_weight=Decimal(tare), status='AVAILABLE', active=True)
        db.add(m); add(m, 200, 700)
    for n in range(1, N_SACK1 + 1):
        m = CollectionMedium(type_id=types['SACK_1KG'].id, code=f'DEMO-S1-{n}', tare_weight=Decimal(1), status='AVAILABLE', active=True)
        db.add(m); add(m, 15, 60)
    for n in range(1, N_SACK2 + 1):
        m = CollectionMedium(type_id=types['SACK_2KG_UN'].id, code=f'DEMO-S2-{n}', tare_weight=Decimal(2), status='AVAILABLE', active=True)
        db.add(m); add(m, 15, 60)
    for code, kg in BULK:
        plan.append((None, cats[code], kg, 'BULK'))
    db.flush()
    total = sum(p[2] for p in plan)
    trip = InboundTrip(receipt_number=RECEIPT, receipt_type='CURTAIN_TRAILER', receipt_date=now, status='CLOSED', created_by=user.id, notes=TAG)
    db.add(trip); db.flush()
    load = InboundLoad(trip_id=trip.id, load_sequence=1, supplier_id=sup, order_number=TAG, status='CLOSED', net_weight=Decimal(total), notes=TAG, ready_for_sorting_at=now)
    db.add(load); db.flush()
    ses = SortingSession(inbound_load_id=load.id, status='CLOSED', started_at=now, started_by=user.id, final_sorting_weight=Decimal(total), final_difference=Decimal(0))
    db.add(ses); db.flush()
    counts = {}
    for m, cat, kg, et in plan:
        e = SortingEntry(session_id=ses.id, weee_category_id=cat.id, collection_medium_id=m.id if m else None, entry_type=et,
                         raw_weight=Decimal(kg), created_by=user.id, notes=TAG)
        db.add(e); db.flush()
        appmain._sync_entry_stock(db, e, user)
        key = (types_by_id(types, m.type_id) if m else 'BULK')
        counts[key] = counts.get(key, 0) + 1
    db.commit()
    print('Δημιουργήθηκαν DEMO εγγραφές ανά κατηγορία:')
    names = {'BASKET_LARGE': 'Καλάθι μεγάλο', 'BASKET_SMALL': 'Καλάθι μικρό', 'INFOCYCLE_1': 'Infocycle 1 (νέα DEMO μέσα)', 'INFOCYCLE_2': 'Infocycle 2',
             'PALLET': 'Παλέτες (νέα DEMO μέσα)', 'SACK_1KG': 'Σάκοι 1 kg (νέα DEMO μέσα)', 'SACK_2KG_UN': 'Σάκοι 2 kg (νέα DEMO μέσα)', 'BULK': 'Χύμα'}
    for k, v in counts.items(): print(f'  {names.get(k, k)}: {v}')
    print(f'Σύνολο {sum(counts.values())} εγγραφές, {total} kg καθαρά, {len({p[1].id for p in plan})} διαφορετικές κατηγορίες ΑΗΗΕ.')


def types_by_id(types, tid):
    for c, t in types.items():
        if t.id == tid: return c
    return '?'


def demo_ids(db):
    trip = demo_trip(db)
    if not trip: return None
    loads = db.scalars(select(InboundLoad.id).where(InboundLoad.trip_id == trip.id)).all()
    sess = db.scalars(select(SortingSession.id).where(SortingSession.inbound_load_id.in_(loads))).all()
    ents = db.scalars(select(SortingEntry.id).where(SortingEntry.session_id.in_(sess))).all()
    lots = db.scalars(select(WEEEStockLot).where(WEEEStockLot.source_sorting_entry_id.in_(ents))).all()
    return trip, loads, sess, ents, lots


def status(db):
    d = demo_ids(db)
    if not d: print('Δεν υπάρχουν DEMO δεδομένα.'); return
    trip, loads, sess, ents, lots = d
    media = db.scalars(select(CollectionMedium).where(CollectionMedium.code.like('DEMO-%'))).all()
    cons = [l for l in lots if Decimal(l.available_weight) < Decimal(l.original_weight)]
    print(f'DEMO: {len(lots)} lots ({sum(float(l.original_weight) for l in lots)} kg), {len(media)} νέα DEMO μέσα, {len(cons)} lots που έχουν περάσει (μερικώς) στην Παραγωγή.')


def delete_materials_demo(db):
    """Σβήνει ΜΟΝΟ τα DEMO του Android → ΥΛΙΚΑ (εξαγωγές, ζυγίσεις απογραφής, μέσα DEMO-P-/DEMO-S-). Τα DEMO καλάθια/παραλαβή μένουν."""
    mlots = db.scalars(select(models.ReadyMaterialLot).where(models.ReadyMaterialLot.is_demo == True)).all()
    mids = [l.id for l in mlots]
    if mids:
        db.execute(sa_delete(models.ReadyMaterialMovement).where(models.ReadyMaterialMovement.lot_id.in_(mids)))
        db.execute(sa_delete(models.ReadyMaterialLot).where(models.ReadyMaterialLot.id.in_(mids)))
    n_inv = db.execute(sa_delete(models.MaterialInventoryEntry).where(models.MaterialInventoryEntry.is_demo == True)).rowcount or 0
    db.execute(sa_delete(models.AppSetting).where(models.AppSetting.key.like('matmedium.seq.DEMO-%')))
    db.flush()
    n_media = 0
    for m in db.scalars(select(CollectionMedium).where((CollectionMedium.code.like('DEMO-P-%')) | (CollectionMedium.code.like('DEMO-S-%')))).all():
        db.delete(m); n_media += 1
    db.commit()
    print(f'Σβήστηκαν (ΥΛΙΚΑ DEMO): {len(mids)} εξαγωγές, {n_inv} ζυγίσεις απογραφής, {n_media} DEMO μέσα.')


def delete(db, with_transfers=False):
    delete_materials_demo(db)
    d = demo_ids(db)
    media_demo = db.scalars(select(CollectionMedium).where(CollectionMedium.code.like('DEMO-%'))).all()
    has_mat = db.scalar(select(func.count()).select_from(models.ReadyMaterialLot).where(models.ReadyMaterialLot.is_demo == True)) or db.scalar(select(func.count()).select_from(models.MaterialInventoryEntry).where(models.MaterialInventoryEntry.is_demo == True))
    if not d and not media_demo and not has_mat: print('Δεν υπάρχουν DEMO δεδομένα.'); return
    trip, loads, sess, ents, lots = d if d else (None, [], [], [], [])
    lot_ids = [l.id for l in lots]
    items = db.scalars(select(ProductionTransferItem).where(ProductionTransferItem.stock_lot_id.in_(lot_ids))).all() if lot_ids else []
    if items and not with_transfers:
        print(f'Σταματάω: {len(items)} μεταφορές DEMO κιλών έχουν περάσει στην Παραγωγή. Για να σβηστούν και αυτές τρέξε:  demo_data.py delete --and-transfers'); return
    if items:
        outs = db.scalar(select(func.count()).select_from(models.DirectProcessingEvent).where(models.DirectProcessingEvent.source_stock_lot_id.in_(lot_ids))) if hasattr(models, 'DirectProcessingEvent') else 0
        if outs:
            print('Σταματάω: υπάρχουν έτοιμα υλικά που προήλθαν από DEMO κιλά (δεν σβήνονται αυτόματα).'); return
        tids = {i.transfer_id for i in items}
        item_ids = [i.id for i in items]
        db.execute(sa_delete(ProductionInputBalance).where(ProductionInputBalance.transfer_item_id.in_(item_ids)))
        db.execute(sa_delete(ProductionWorkEntry).where(ProductionWorkEntry.transfer_id.in_(tids)))
        db.execute(sa_delete(ProductionTransferItem).where(ProductionTransferItem.id.in_(item_ids)))
        for tid in tids:
            if not db.scalar(select(func.count()).select_from(ProductionTransferItem).where(ProductionTransferItem.transfer_id == tid)):
                db.execute(sa_delete(ProductionTransfer).where(ProductionTransfer.id == tid))
    used_media = {l.collection_medium_id for l in lots if l.collection_medium_id}
    if lot_ids:
        db.execute(sa_delete(StockMovement).where(StockMovement.lot_id.in_(lot_ids)))
        db.execute(sa_delete(WEEEStockLot).where(WEEEStockLot.id.in_(lot_ids)))
    if ents:
        db.execute(sa_delete(models.SortingAdjustment).where(models.SortingAdjustment.sorting_entry_id.in_(ents)))
        db.execute(sa_delete(SortingEntry).where(SortingEntry.id.in_(ents)))
    if sess: db.execute(sa_delete(SortingSession).where(SortingSession.id.in_(sess)))
    if loads: db.execute(sa_delete(InboundLoad).where(InboundLoad.id.in_(loads)))
    if trip: db.execute(sa_delete(InboundTrip).where(InboundTrip.id == trip.id))
    n_media = 0
    for m in media_demo:
        db.delete(m); n_media += 1
    db.flush()
    for mid in used_media:  # υπάρχοντα καλάθια του Μητρώου -> ξανά «διαθέσιμα»
        m = db.get(CollectionMedium, mid)
        if m and m.status == 'WEEE_STORAGE' and not db.scalar(select(func.count()).select_from(WEEEStockLot).where(WEEEStockLot.collection_medium_id == mid, WEEEStockLot.available_weight > 0)):
            m.status = 'AVAILABLE'
    db.commit()
    print(f'Σβήστηκαν: {len(lot_ids)} DEMO lots, {len(ents)} εγγραφές ταξινόμησης, 1 DEMO παραλαβή, {n_media} DEMO μέσα. Τα υπάρχοντα καλάθια ξαναγύρισαν σε «διαθέσιμο».')



def create_warehouse_demo(db):
    """DEMO για Windows → Υλικά → Αποθήκη: εξαγωγές (παλέτες/σάκοι/χύμα), ζυγίσεις απογραφής και ένα μέσο απογραφής που εξήχθη (280 → 310 kg)."""
    from app import mat_warehouse as mw
    from decimal import Decimal as D
    if db.scalar(select(func.count()).select_from(models.ReadyMaterialLot).where(models.ReadyMaterialLot.is_demo == True)):
        print('Υπάρχουν ήδη DEMO υλικά. Σβήσε πρώτα (κουμπί «Σβήσιμο DEMO» ή delete-materials).'); return
    user = db.scalars(select(User)).first()
    mats, seen = [], set()
    for m in db.scalars(select(models.Material).where(models.Material.storage_group_id.is_not(None)).order_by(models.Material.internal_name)).all():
        if m.storage_group_id not in seen:
            seen.add(m.storage_group_id); mats.append(m)
        if len(mats) >= 4: break
    y, q, mo = mw._period(); loc = mw._location(db)
    def lot(m, form, net, tare=None, inv=None, counted=None):
        md = mw._new_medium(db, form, tare, True, 'READY_STORAGE') if form != 'BULK' else None
        l = models.ReadyMaterialLot(lot_number=mw._lot_number(db, m, True), material_id=m.id, output_form=('CONTAINER' if md else 'BULK'), collection_medium_id=md.id if md else None,
            tare_weight=tare, net_weight=D(str(net)), location_id=loc.id, status='DEMO', created_by=user.id, notes='DEMO', entry_type='EXPORT',
            period_year=y, period_quarter=q, period_month=mo, counted_kg=D(str(counted if counted is not None else net)), storage_group_id=m.storage_group_id,
            source_inventory_id=inv, is_demo=True)
        db.add(l); db.flush()
        db.add(models.ReadyMaterialMovement(lot_id=l.id, movement_type='PRODUCTION_OUT', weight=D(str(net)), user_id=user.id, reason='DEMO'))
        return l, md
    def inv(m, form, net, tare=None):
        md = mw._new_medium(db, form, tare, True, 'READY_STORAGE') if form != 'BULK' else None
        e = models.MaterialInventoryEntry(material_id=m.id, storage_group_id=m.storage_group_id, collection_medium_id=md.id if md else None, form=form, tare_weight=tare,
            net_weight=D(str(net)), year=y, quarter=q, month=mo, status='COUNTED', is_demo=True, created_by=user.id)
        db.add(e); db.flush(); return e
    for i, m in enumerate(mats):
        lot(m, 'PALLET', 410 + 35 * i, 25); lot(m, 'PALLET', 520 - 20 * i, 25)
        lot(m, 'SACK_1KG', 18 + i, 1); lot(m, 'SACK_2KG', 37 + i, 2); lot(m, 'BULK', 60 + 10 * i)
        inv(m, 'PALLET', 300 + 15 * i, 25); inv(m, 'SACK_1KG', 20, 1)
    m0 = mats[0]; e = inv(m0, 'PALLET', 280, 25); e.status = 'EXPORTED'
    l, _ = lot(m0, 'PALLET', 310, 25, inv=e.id, counted=30); e.exported_lot_id = l.id; e.collection_medium_id = l.collection_medium_id
    db.commit()
    print(f'DEMO υλικά αποθήκης για {len(mats)} υλικά ({", ".join((m.official_description or m.internal_name) for m in mats)}).')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    with SessionLocal() as db:
        if cmd == 'create': create(db)
        elif cmd == 'delete': delete(db, with_transfers='--and-transfers' in sys.argv)
        elif cmd == 'delete-materials': delete_materials_demo(db)
        elif cmd == 'warehouse-demo': create_warehouse_demo(db)
        else: status(db)
