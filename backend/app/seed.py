from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Permission, Role, User, Person, OrganizationalUnit, Organization, WEEECategory, Material, CollectionMediumType, CollectionMedium, ContainerAsset, AppSetting, InventoryLocation, OrganizationRegistryDetail, SupplierBranch, organization_roles
from .security import hash_password
from .config import settings
import json
from pathlib import Path
from decimal import Decimal

PERMISSIONS = [
    ("master.view","Προβολή master data"),("master.edit","Επεξεργασία master data"),
    ("receipt.view","Προβολή παραλαβών"),("receipt.create","Δημιουργία παραλαβής"),("receipt.edit","Επεξεργασία παραλαβής"),
    ("sorting.perform","Εκτέλεση ταξινόμησης"),("sorting.review","Έλεγχος Logistics"),("sorting.approve","Έγκριση Διοίκησης"),
    ("production.view","Προβολή παραγωγής"),("production.move","Κινήσεις παραγωγής"),("production.edit","Διόρθωση καταχωρίσεων παραγωγής"),
    ("loading.view","Προβολή φορτώσεων"),("loading.execute","Εκτέλεση φόρτωσης"),
    ("people.attendance","Παρουσίες/μετακινήσεις προσωπικού"),
    ("galaxy.view","Προβολή Galaxy sync"),("galaxy.manage","Διαχείριση Galaxy sync"),
    ("quality.manage","Διαχείριση Quality/Compliance"),("reports.manage","Διαχείριση reports/templates"),
    ("equipment.view","Προβολή εξοπλισμού/ΜΑΠ/αναλωσίμων"),("equipment.edit","Διαχείριση εξοπλισμού/ΜΑΠ/αναλωσίμων"),
    ("settings.manage","Ρυθμίσεις"),("users.manage","Χρήστες/δικαιώματα"),("audit.view","Προβολή audit"),("*","Πλήρης πρόσβαση"),
]
ROLE_MAP = {
    "SORTING": ("Ταξινόμηση", ["master.view","receipt.view","sorting.perform"]),
    "FORKLIFT": ("Χειριστής", ["master.view","receipt.view","sorting.perform","production.view","production.move","loading.view","loading.execute","people.attendance"]),
    "LOGISTICS": ("Logistics / Γραφείο Κίνησης", ["master.view","master.edit","receipt.view","receipt.create","receipt.edit","sorting.review","production.view","production.move","production.edit","loading.view","galaxy.view","galaxy.manage","reports.manage","people.attendance","audit.view","equipment.view","equipment.edit"]),
    "QUALITY": ("Διαχείριση Ποιότητας", ["master.view","quality.manage","reports.manage","galaxy.view","galaxy.manage","audit.view"]),
    "MANAGEMENT": ("Διοίκηση", ["*"]),
}
ORG_UNITS = [
    ("TV","Τμήμα Τηλεόρασης"),("BENCH","Τμήμα Πάγκων"),("TELCO","Τμήμα Τηλεπικοινωνιών"),
    ("WH_AC","Τμήμα Θερμοσιφώνων & Κλιματιστικών"),("LARGE","Τμήμα Μεγάλων Συσκευών"),
    ("PRESS","Πρέσα"),("BELT","Ταινία Διαλογής"),("DEPOLLUTION","Απορρύπανση"),
    ("SORTING_DEPT","Τμήμα Ταξινόμησης"),("OPERATORS","Χειριστές"),("EXTERNAL","Τμήμα Εξωτερικών"),("MANAGEMENT_DEPT","Διοίκηση"),
]
WEEE = [
("1Α1100","Ψυγεία - Καταψύκτες Οικιακού τύπου full (unknown insulation)","62.2"),
("1Α1200","Ψυγεία - Καταψύκτες Οικιακού τύπου no (unknown insulation)","48.9"),
("1Α2100","Ψυγεία - καταψύκτες Μη Οικιακού τύπου κατ.5 full (unknown insulation)","84"),
("1Α2200","Ψυγεία - καταψύκτες Μη Οικιακού τύπου κατ.5 no (unknown insulation)","100"),
("1Α3000","Ψυγεία Αμμωνίας","10"),("1Β1100","Κλιματιστικά Οικιακού και Φορητού τύπου (Εσωτερικές μονάδες)","9.8"),
("1Β1210","Κλιματιστικά Οικιακού και Φορητού τύπου (Εξωτερικές μονάδες) full","42.9"),
("1Β1220","Κλιματιστικά Οικιακού και Φορητού τύπου (Εξωτερικές μονάδες) no","42.4"),
("1Β1300","Κλιματιστικά Οικιακού και Φορητού τύπου (Αυτόνομες / Φορητές μον.)","57"),
("1Β2100","Κλιματιστικά Μη-Οικιακού και Μεγάλου τύπου (Εσωτερικές μονάδες)","33.85"),
("1Β2200","Κλιματιστικά Μη-Οικιακού και Μεγάλου τύπου (Εξωτερικές μονάδες)","47"),
("1Γ0000","Εξοπλισμός που περιέχει έλαια","18.9"),("1Δ0000","Διανομείς με ψύξη - κατάψυξη (unknown insulation)","13"),
("1Ε0000","Αφυγραντήρες","15.9"),("1Ζ0000","Άλλος εξοπλισμός με ρευστά (εκτός νερού)","8"),
("2Α1110","Οθόνες (Τηλεοράσεις) FPD full (unknown type)","16.7"),("2Α1120","Οθόνες (Τηλεοράσεις) FPD no (unknown type)","16.7"),
("2Α1210","Οθόνες (Monitor) FPD full (unknown type)","4.9"),("2Α1220","Οθόνες (Monitor) FPD no (unknown type)","4.9"),
("2Α2110","Οθόνες (Τηλεοράσεις) CRT full","22.8"),("2Α2120","Οθόνες (Τηλεοράσεις) CRT no","19.3"),
("2Α2210","Οθόνες (Monitor) CRT full","15.2"),("2Α2220","Οθόνες (Monitor) CRT no","13.3"),
("2Β1000","Laptops/Notebooks","2.9"),("2Β2000","Tablets","0.8"),("2Β3000","Παιχνιδομηχανές με οθόνη","84.9"),("2Β4000","Λοιπός εξοπλισμός με οθόνη",None),
("3Α0000","Λαμπτήρες εκκένωσης αερίων (unknown type)","0.3"),("3Β0000","Λαμπτήρες LED","0.1"),
("4Α1000","Κουζίνες","40.9"),("4Α2110","Πλυντήρια Οικιακού τύπου full","60.6"),("4Α2120","Πλυντήρια Οικιακού τύπου no","57.2"),
("4Α2200","Πλυντήρια Επαγγελματικού τύπου",None),("4Α3100","Θερμοσίφωνες OTHER","29"),("4Α3200","Θερμοσίφωνες PU","32.21"),
("4Β0000","Σκούπες - Σίδερα - Πιστολάκια - Καφετιέρες","5.2"),("4Γ0000","PV PANELS (unknown type)",None),("4Δ0000","Ήχος- Εικόνα (Radio - CD - DVD - Ηχεία)","9.4"),
("4Ε0000","Φωτιστικά είδη","9.3"),("4Ζ0000","Εργαλεία","12.6"),("4Η0000","Παιχνίδια","10.2"),("4Θ0000","Ιατρικά",None),
("4Ι0000","Παρακολούθηση & έλεγχος",None),("4Κ1000","Αυτόματοι Διανομείς (ΑΤΜ)","624.6"),("4Κ2000","Αυτόματοι Διανομείς (Λοιποί)","410.7"),("4Λ0000","PC - Server / IT μεγάλης κατηγορίας","8.6"),
("5Α0000","Κουζινάκια - μικροκυμάτων - ανεμιστήρες","8.9"),("5Β0000","Σκούπες - Σίδερα - Πιστολάκια - Καφετιέρες","1"),("5Β1000","Ηλεκτρονικά Τσιγάρα","0.024"),
("5Γ0000","PV Panels (unknown type)",None),("5Δ0000","Radio- CD - Video - Ενισχυτές - Κάμερες","1.29"),("5Ε0000","Φωτιστικά είδη","1.29"),("5Ζ0000","Εργαλεία","2.5"),
("5Η0000","Παιχνίδια","11.6"),("5Θ0000","Ιατρικά","0.3"),("5Ι1100","Ανιχνευτές καπνού Ραδιενεργοί","0.2"),("5Ι1200","Ανιχνευτές καπνού Μη Ραδιενεργοί","0.2"),
("5Ι2000","Παρακολούθηση & έλεγχος (λοιπός εξοπλισμός)","15.1"),("5Κ0000","Αυτόματοι Διανομείς","4.8"),
("6Α0000","PC - Server / IT μικρής κατηγορίας","8.6"),("6Β0000","Παιχνιδομηχανές (Κονσόλες)","3.5"),("6Γ0000","Κινητά τηλέφωνα","0.2"),
("6Δ1000","Τόνερ (unknown type)","1.1"),("6Δ2000","Μελάνια (unknown type)","0.3"),("6Ε0000","Καλώδια","0.1"),
]
ERP_MATERIALS = [
("V00109","ΑΚΑΘΑΡΙΣΤΟ ΧΥΔΗΝ","16.02.16","19 12 12 /01"),
("Α00001","ΣΙΔΗΡΟΣ","19.12.02","16 02 16 / 02"),
("Α00002Γ","ΣΕΡΠΑΤΙΝΑ ΚΑΘΑΡΗ","19.12.03","19 12 03 / 02-2"),
("Α00008","ΧΑΛΚΟΣ","19.12.03","16 02 16 / 06"),
("Α00012","ΜΕΤΑΣΧΗΜΑΤΙΣΤΕΣ ΤΑΣΗΣ","16.02.16","16 02 16 / 11"),
("Α00020","INOX","19.12.02","16 02 16 / 02"),
("Α00047","ΑΛΟΥΜΙΝΙΟ ΠΡΟΦΙΛ","19.12.03","16 02 16 / 04"),
("Α00059","ΠΛΑΣΤΙΚΟ ΑΣΠΡΟ","19.12.04","16 02 16 / 31"),
("Α00060","ΠΛΑΣΤΙΚΟ ΜΑΥΡΟ","19.12.04","16 02 16 / 31"),
("Α00061","ΠΛΑΣΤΙΚΟ ΑΝΑΜΕΙΚΤΟ","19.12.04","16 02 16 / 31"),
("Α00073","ΜΟΤΕΡ ΜΙΚΡΑ","16.02.16","16 02 16 / 11"),
("Α00074","PLEXIGLASS","19.12.04","16 02 16 / 31"),
("Α00076","ΜΟΤΕΡ ΜΕΓΑΛΑ","16.02.16","16 02 16 / 11"),
("Α00202","ΣΥΜΠΙΕΣΤΕΣ","16.02.16","16 02 16 / 12"),
]

def seed(db: Session):
    perms = {}
    for code,desc in PERMISSIONS:
        p=db.scalar(select(Permission).where(Permission.code==code))
        if not p:
            p=Permission(code=code,description=desc); db.add(p); db.flush()
        perms[code]=p
    for code,(name,codes) in ROLE_MAP.items():
        r=db.scalar(select(Role).where(Role.code==code))
        if not r:
            r=Role(code=code,name_el=name); db.add(r); db.flush()
        r.permissions=[perms[c] for c in codes]
    db.flush()
    for i,(code,name) in enumerate(ORG_UNITS,1):
        if not db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code==code)):
            db.add(OrganizationalUnit(code=code,name_el=name,sort_order=i))
    for code,desc,avg in WEEE:
        if not db.scalar(select(WEEECategory).where(WEEECategory.code==code)):
            db.add(WEEECategory(code=code,description_el=desc,average_weight=avg))
    # Company-only operator subcategories. These are display/operational children of an
    # official WEEE parent and NEVER become new official reporting codes.
    company_subcategories = [
        # Exact company incoming-material hierarchy; order is intentional.
        ("INT-4D-AUDIO", "Ήχος- Εικόνα (Radio - CD - DVD - Ηχεία)", "4Δ0000"),
        ("INT-4D-PROJ", "Projectors", "4Δ0000"),
        ("INT-4I-UPS", "UPS", "4Ι0000"),
        ("INT-4I-MON", "Παρακολούθηση & έλεγχος - Συναγερμοί", "4Ι0000"),
        ("INT-4I-CASH", "Ταμειακές - Καταμετρικές", "4Ι0000"),
        ("INT-4L-PCSERVER", "PC - Server", "4Λ0000"),
        ("INT-4L-PRINT", "Εκτυπωτές - Fax - Τηλεπικοινωνίες", "4Λ0000"),
        ("INT-4L-SCAN", "Scanner", "4Λ0000"),
        ("INT-4L-COPY", "Φωτοτυπικά", "4Λ0000"),
        ("INT-4L-KEYB", "Πληκτρολόγια - ποντίκια", "4Λ0000"),
        ("INT-5D-AV", "Radio- CD - Video - Ενισχυτές - Κάμερες", "5Δ0000"),
        ("INT-5D-SPEAK", "Ηχεία", "5Δ0000"),
        ("INT-5D-PROJ", "Projectors", "5Δ0000"),
        ("INT-5I2-UPS", "UPS", "5Ι2000"),
        ("INT-5I2-MON", "Παρακολούθηση & έλεγχος - Συναγερμοί", "5Ι2000"),
        ("INT-5I2-CASH", "Ταμειακές - Καταμετρικές", "5Ι2000"),
        ("INT-6A-PCSERVER", "PC - Server", "6Α0000"),
        ("INT-6A-PRINT", "Εκτυπωτές - fax - scanner", "6Α0000"),
        ("INT-6A-MODEM", "Modem - router", "6Α0000"),
        ("INT-6A-KEYB", "Πληκτρολόγια - ποντίκια", "6Α0000"),
        ("INT-6A-TELCO", "Τηλεπικοινωνίες - τηλέφωνα - συσκ. καρτών", "6Α0000"),
    ]
    for code,desc,parent in company_subcategories:
        obj=db.scalar(select(WEEECategory).where(WEEECategory.code==code))
        if not obj:
            db.add(WEEECategory(code=code,description_el=desc,parent_code=parent,is_internal_subcategory=True))
        else:
            obj.description_el=desc; obj.parent_code=parent; obj.is_internal_subcategory=True; obj.active=True
    managed_parents={"4Δ0000","4Ι0000","4Λ0000","5Δ0000","5Ι2000","6Α0000"}
    allowed_internal={x[0] for x in company_subcategories}
    for obj in db.scalars(select(WEEECategory).where(WEEECategory.is_internal_subcategory==True)).all():
        if obj.parent_code in managed_parents and obj.code not in allowed_internal:
            obj.active=False
    # Build 1.6 mistakenly seeded operational 'Χύμα' rows as WEEE categories.
    # Do not create such material codes. Hide legacy rows only when present.
    for legacy in ("INT-BULK-FRIDGE","INT-BULK-FREEZER"):
        obj=db.scalar(select(WEEECategory).where(WEEECategory.code==legacy))
        if obj: obj.active=False
    for code,name,eka,rep in ERP_MATERIALS:
        if not db.scalar(select(Material).where(Material.internal_code==code)):
            db.add(Material(internal_code=code,internal_name=name,galaxy_code=code,galaxy_description=name,eka_code=eka,reptool_code=rep))
    medium_types=[
        ("INFOCYCLE_1","Καλάθια Infocycle 1",None,True,False),
        ("INFOCYCLE_2","Καλάθια Infocycle 2",None,True,False),
        ("BASKET_LARGE","Καλάθια μεγάλα",None,True,False),
        ("BASKET_SMALL","Καλάθια μικρά",None,True,False),
        ("SACK_1KG","Σάκος 1kg","1",True,True),
        ("SACK_2KG_UN","Σάκος 2kg / UN","2",True,True),
        ("PALLET","Παλέτα",None,True,False),
        ("BOX","Πλαστικό κουτί",None,False,False),
        ("BULK","Χύμα",None,False,False),
        # legacy type retained for existing databases / unique big-bag numbering
        ("BIG_BAG","Μεγασάκος",None,True,True),
        # Υλικά storage media (σακός/παλέτα) -- kept separate from the ΑΗΗΕ-side PALLET/SACK_* types
        # above so materials numbering never collides with or is affected by ΑΗΗΕ warehouse usage.
        ("MATERIAL_SACK","Σακός Υλικών",None,True,True),
        ("MATERIAL_PALLET","Παλέτα Υλικών",None,True,True),
    ]
    for code,name,tare,req,never in medium_types:
        obj=db.scalar(select(CollectionMediumType).where(CollectionMediumType.code==code))
        if not obj:
            db.add(CollectionMediumType(code=code,name_el=name,default_tare_weight=tare,requires_unique_number=req,never_reuse_number=never))
        else:
            obj.name_el=name; obj.default_tare_weight=tare; obj.requires_unique_number=req; obj.never_reuse_number=never
            if not db.scalar(select(AppSetting).where(AppSetting.key=='medium_type.deleted.'+code)): obj.active=True   # είδος που διέγραψε ο χρήστης δεν ξαναενεργοποιείται
    for legacy_code in ("METAL_BASKET","BIG_BAG","SACK_2KG"):
        # SACK_2KG is a legacy duplicate of SACK_2KG_UN.
        legacy=db.scalar(select(CollectionMediumType).where(CollectionMediumType.code==legacy_code))
        if legacy: legacy.active=False
    db.flush()
    # Build 1.8: the supplied operational registries are real Master Data, not reference-only files.
    data_dir=Path(__file__).resolve().parent / "data"
    # Build 2.5.34: authoritative Materials profile import from the supplied ERP list.
    # This runs once per persistent database so later user edits are preserved.
    mat_rev_key="materials.profile.import.rev2536_her_eka_reptool_backfill"
    mat_rev=db.scalar(select(AppSetting).where(AppSetting.key==mat_rev_key))
    mat_path=data_dir / "material_registry_2534.json"
    if mat_path.exists() and not mat_rev:
        rows=json.loads(mat_path.read_text(encoding="utf-8"))
        for row in rows:
            galaxy=(row.get("galaxy_code") or "").strip() or None
            obj=db.scalar(select(Material).where(Material.galaxy_code==galaxy)) if galaxy else None
            if not obj:
                key=galaxy or f"REF-{int(row.get('source_index') or 0):04d}"
                obj=db.scalar(select(Material).where(Material.internal_code==key))
            if not obj:
                obj=Material(internal_code=(galaxy or f"REF-{int(row.get('source_index') or 0):04d}"), internal_name=(row.get("official_description") or galaxy or "Υλικό"))
                db.add(obj); db.flush()
            obj.galaxy_code=galaxy
            obj.galaxy_description=row.get("official_description") or obj.galaxy_description
            obj.official_description=row.get("official_description") or obj.official_description
            obj.genre=row.get("genre") or obj.genre
            # Do not overwrite trusted legacy HER/EKA/Reptool values with blanks from the pasted source.
            if row.get("her_description"): obj.her_description=row.get("her_description")
            if row.get("eka_code"): obj.eka_code=row.get("eka_code")
            if row.get("reptool_code"): obj.reptool_code=row.get("reptool_code")
            if row.get("reptool_description"): obj.reptool_description=row.get("reptool_description")
            obj.is_precious=bool(row.get("is_precious"))
            obj.export_step_kg=Decimal("0.050") if obj.is_precious else Decimal("0.500")
            obj.active=bool(galaxy)
            if obj.galaxy_description: obj.internal_name=obj.galaxy_description
        db.add(AppSetting(key=mat_rev_key,value="done"))
        db.flush()
    info_path=data_dir / "infocycle2_registry.json"
    if info_path.exists():
        mt=db.scalar(select(CollectionMediumType).where(CollectionMediumType.code=="INFOCYCLE_2"))
        for row in json.loads(info_path.read_text(encoding="utf-8")):
            code=str(row.get("code","")).strip()
            if not code: continue
            obj=db.scalar(select(CollectionMedium).where(CollectionMedium.type_id==mt.id, CollectionMedium.code==code)) or db.scalar(select(CollectionMedium).where(CollectionMedium.type_id==mt.id, CollectionMedium.code==f"I2-{code}"))
            if not obj:
                # Prefix only when a legacy medium already owns the same global code. UI still shows the registry number.
                existing=db.scalar(select(CollectionMedium).where(CollectionMedium.code==code))
                stored=code if not existing else f"I2-{code}"
                obj=CollectionMedium(type_id=mt.id,code=stored,tare_weight=row.get("tare_kg"),status="AVAILABLE",active=True)
                db.add(obj); db.flush()
            else:
                obj.tare_weight=row.get("tare_kg"); obj.active=True
    ctr_path=data_dir / "container_registry.json"
    if ctr_path.exists():
        for row in json.loads(ctr_path.read_text(encoding="utf-8")):
            carrier=str(row.get("carrier","")).strip(); code=str(row.get("code","")).strip()
            if not carrier or not code: continue
            org=db.scalar(select(Organization).where(Organization.legal_name==carrier))
            if not org:
                org=Organization(legal_name=carrier,trade_name=carrier,active=True); db.add(org); db.flush()
            # Registry owners are carriers and must be selectable in Receiving.
            from . import models as _models
            exists=db.execute(select(_models.organization_roles.c.organization_id).where(_models.organization_roles.c.organization_id==org.id,_models.organization_roles.c.role=="CARRIER")).first()
            if not exists:
                db.execute(_models.organization_roles.insert().values(organization_id=org.id,role="CARRIER"))
            # ContainerAsset currently has a global unique key. Keep an internal composite key,
            # while the UI exposes only the real registry code and carrier.
            stored=f"{org.id[:8]}::{code}"
            obj=db.scalar(select(ContainerAsset).where(ContainerAsset.container_number==stored))
            if not obj:
                db.add(ContainerAsset(container_number=stored,owner_organization_id=org.id,tare_weight=row.get("tare_kg") or 0,status="AVAILABLE",active=True,notes=f"REGISTRY_CODE={code}")); db.flush()
            else:
                obj.tare_weight=row.get("tare_kg") or 0; obj.active=True; obj.notes=f"REGISTRY_CODE={code}"
    # Build 2.4: supplied counterparty and supplier/branch registries are real Master Data.
    counterparty_path=data_dir / "counterparty_registry.json"
    if counterparty_path.exists():
        for row in json.loads(counterparty_path.read_text(encoding="utf-8")):
            name=str(row.get("name","")).strip(); tax=str(row.get("tax_id","")).strip() or None
            if not name: continue
            org=db.scalar(select(Organization).where(Organization.tax_id==tax)) if tax else None
            if not org:
                org=db.scalar(select(Organization).where(Organization.legal_name==name))
            if not org:
                org=Organization(legal_name=name,trade_name=name,tax_id=tax,phone=(row.get("phone1") or None),active=True); db.add(org); db.flush()
            else:
                if tax and not org.tax_id: org.tax_id=tax
                if row.get("phone1") and not org.phone: org.phone=row.get("phone1")
            # Generic counterparty registry is exposed under Partners; supplier/carrier roles can coexist.
            exists=db.execute(select(organization_roles.c.organization_id).where(organization_roles.c.organization_id==org.id,organization_roles.c.role=="PARTNER")).first()
            if not exists: db.execute(organization_roles.insert().values(organization_id=org.id,role="PARTNER"))
            detail=db.scalar(select(OrganizationRegistryDetail).where(OrganizationRegistryDetail.organization_id==org.id))
            vals=dict(external_code=row.get("code") or None,phone2=row.get("phone2") or None,street=row.get("street") or None,street_number=row.get("street_number") or None,municipality=row.get("municipality") or None,prefecture=row.get("prefecture") or None,country_code=row.get("country_code") or None,profession=row.get("profession") or None,transaction_code=row.get("transaction_code") or None)
            if not detail: detail=OrganizationRegistryDetail(organization_id=org.id,**vals); db.add(detail)
            else:
                for k,v in vals.items(): setattr(detail,k,v)
    supplier_branch_path=data_dir / "supplier_branches_registry.json"
    if supplier_branch_path.exists():
        for row in json.loads(supplier_branch_path.read_text(encoding="utf-8")):
            name=str(row.get("supplier","")).strip(); tax=str(row.get("tax_id","")).strip() or None; branch=str(row.get("branch","")).strip()
            if not name or not branch: continue
            org=db.scalar(select(Organization).where(Organization.tax_id==tax)) if tax else None
            if not org: org=db.scalar(select(Organization).where(Organization.legal_name==name))
            if not org:
                org=Organization(legal_name=name,trade_name=name,tax_id=tax,active=True); db.add(org); db.flush()
            exists=db.execute(select(organization_roles.c.organization_id).where(organization_roles.c.organization_id==org.id,organization_roles.c.role=="SUPPLIER")).first()
            if not exists: db.execute(organization_roles.insert().values(organization_id=org.id,role="SUPPLIER"))
            b=db.scalar(select(SupplierBranch).where(SupplierBranch.supplier_id==org.id,SupplierBranch.name==branch))
            if not b: db.add(SupplierBranch(supplier_id=org.id,name=branch,active=True))
            else: b.active=True

    inventory_locations=[
        ("WEEE_MAIN","Αποθήκη ΑΗΗΕ προς ανακύκλωση","WEEE"),
        ("PRODUCTION_FLOOR","Χώρος Παραγωγής","PRODUCTION"),
        ("READY_MAIN","Αποθήκη Υλικών προς Φόρτωση","READY_MATERIAL"),
    ]
    for code,name,domain in inventory_locations:
        if not db.scalar(select(InventoryLocation).where(InventoryLocation.code==code)):
            db.add(InventoryLocation(code=code,name_el=name,domain=domain))

    settings_data={
        "app.language.default":"el",
        "sorting.deadline.business_days":"2",
        "sorting.rounding.final_only":"true",
        "sorting.weight.minimum_unit_kg":"1",
        "ui.android.large_touch_targets":"true",
        "big_bag.number_prefix":"BB",
        "big_bag.next_sequence":"1",
    }
    for k,v in settings_data.items():
        if not db.scalar(select(AppSetting).where(AppSetting.key==k)):
            db.add(AppSetting(key=k,value=v))
    admin=db.scalar(select(User).where(User.username==settings.bootstrap_admin_username))
    if not admin:
        person=Person(first_name="System",last_name="Administrator"); db.add(person); db.flush()
        admin=User(person_id=person.id,username=settings.bootstrap_admin_username,password_hash=hash_password(settings.bootstrap_admin_password))
        mgmt=db.scalar(select(Role).where(Role.code=="MANAGEMENT")); admin.roles=[mgmt]; db.add(admin)
    db.commit()
