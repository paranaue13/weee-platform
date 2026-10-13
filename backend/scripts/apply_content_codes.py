r"""Εφαρμογή των κωδικών περιεχομένου (3 γράμματα) στη βάση: πίνακες content_codes και content_code_map.

  Έλεγχος (χωρίς αλλαγές):  backend\.venv\Scripts\python.exe backend\scriptspply_content_codes.py
  Εφαρμογή:                 backend\.venv\Scripts\python.exe backend\scriptspply_content_codes.py --apply

ΑΗΗΕ: κωδικός κατηγορίας -> κωδικός περιεχομένου. Υλικά: όνομα κατηγορίας αποθήκης -> κωδικός.
Κάνε πρώτα αντίγραφο της βάσης. Δεν αλλάζει κανένα μέσο ή κωδικό μέσου."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models import Base, ContentCode, ContentCodeMap, CollectionMediumType

WEEE = [
    ('1Α1100', 'FRG', 'Ψυγεία - Καταψύκτες'),
    ('1Α1200', 'FRN', 'Ψυγεία - Καταψύκτες / Χωρίς Μοτέρ'),
    ('1Α2100', 'FRP', 'Ψυγεία - Καταψύκτες / Επαγγελματικά'),
    ('1Α2200', 'FRH', 'Ψυγεία - Καταψύκτες / Επαγγελματικά Χωρίς Μοτέρ'),
    ('1Α3000', 'FRA', 'Ψυγεία Αμμωνίας'),
    ('1Β1210', 'ACX', 'Κλιματιστικά Εξωτερικά'),
    ('1Β1100', 'ACE', 'Κλιματιστικά Εσωτερικά'),
    ('1Β1300', 'ACP', 'Κλιματιστικά Φορητά'),
    ('1Β2200', 'ACC', 'Κλιματιστικά Εξωτερικά / Επαγγελματικά'),
    ('1Β2100', 'ACH', 'Κλιματιστικά Εσωτερικά / Επαγγελματικά'),
    ('1Β1220', 'ACW', 'Κλιματιστικά Εξωτερικά / Χωρίς Μοτέρ'),
    ('4Α2110', 'WMG', 'Πλυντήρια'),
    ('4Α2200', 'WMR', 'Πλυντήρια Επαγγελματικά'),
    ('4Α2120', 'WMN', 'Πλυντήρια Χωρίς Μοτέρ'),
    ('4Α1000', 'KUA', 'Κουζίνες'),
    ('5Α0000', 'MKU', 'Κουζινάκια'),
    ('2Α2210', 'DPC', 'Οθόνες CRT'),
    ('2Α2220', 'DPU', 'Οθόνες CRT / Σπασμένες'),
    ('2Α1210', 'DPF', 'Οθόνες FPD'),
    ('2Α1220', 'DPG', 'Οθόνες FPD / Σπασμένες'),
    ('2Α2120', 'TVC', 'Τηλεοράσεις CRT / Σπασμένες'),
    ('2Α1110', 'TVF', 'Τηλεοράσεις FPD'),
    ('2Α2110', 'TVF', 'Τηλεοράσεις FPD'),
    ('2Α1120', 'TVG', 'Τηλεοράσεις FPD / Σπασμένες'),
    ('2Β1000', 'LAP', 'Laptops'),
    ('2Β2000', 'TPE', 'Tablets'),
    ('6Β0000', 'GMC', 'Παιχνιδομηχανές'),
    ('2Β3000', 'DGM', 'Παιχνιδομηχανές με οθόνη'),
    ('2Β4000', 'XMA', 'Λοιπός εξοπλισμός με οθόνη'),
    ('3Β0000', 'LED', 'Λαμπτήρες LED'),
    ('3Α0000', 'LME', 'Λαμπτήρες εκκένωσης αερίων'),
    ('4Ε0000', 'LGT', 'Φωτιστικά'),
    ('5Ε0000', 'LGT', 'Φωτιστικά'),
    ('4Γ0000', 'PVP', 'Φωτοβολταϊκά'),
    ('5Γ0000', 'PVP', 'Φωτοβολταϊκά'),
    ('4Λ0000', 'PCA', 'PC - Server / IT'),
    ('6Α0000', 'PCA', 'PC - Server / IT'),
    ('5Δ0000', 'AVD', 'Radio - CD - Video - Ενισχυτές - Κάμερες'),
    ('4Δ0000', 'AUV', 'Ήχος - Εικόνα (Radio - CD - DVD - Ηχεία)'),
    ('6Γ0000', 'KNT', 'Κινητά τηλέφωνα'),
    ('6Ε0000', 'WRE', 'Καλώδια'),
    ('6Δ1000', 'TNR', 'Τόνερ'),
    ('6Δ2000', 'MLC', 'Μελάνια'),
    ('109994', 'TCN', 'Τόνερ και μελάνια χωρίς τσιπ'),
    ('5Κ0000', 'VND', 'Αυτόματοι Διανομείς'),
    ('4Κ1000', 'ATA', 'Αυτόματοι Διανομείς (ΑΤΜ)'),
    ('4Κ2000', 'LVN', 'Αυτόματοι Διανομείς (Λοιποί)'),
    ('1Δ0000', 'CDV', 'Διανομείς με ψύξη - κατάψυξη'),
    ('1Ε0000', 'DHA', 'Αφυγραντήρες'),
    ('1Γ0000', 'ELA', 'Εξοπλισμός που περιέχει έλαια'),
    ('1Ζ0000', 'FLE', 'Άλλος εξοπλισμός με ρευστά'),
    ('4Ζ0000', 'ERC', 'Εργαλεία'),
    ('5Ζ0000', 'ERC', 'Εργαλεία'),
    ('5Β1000', 'ECG', 'Ηλεκτρονικά Τσιγάρα'),
    ('4Α3200', 'PUC', 'Θερμοσίφωνες Πολυουρεθάνης'),
    ('4Α3100', 'GLW', 'Θερμοσίφωνες Υαλοβάμβακα'),
    ('4Θ0000', 'MEE', 'Ιατρικά'),
    ('5Θ0000', 'MEE', 'Ιατρικά'),
    ('4Η0000', 'PXD', 'Παιχνίδια'),
    ('5Η0000', 'PXD', 'Παιχνίδια'),
    ('4Ι0000', 'MNF', 'Παρακολούθηση & έλεγχος'),
    ('5Ι2000', 'MNF', 'Παρακολούθηση & έλεγχος'),
    ('5Β0000', 'VCL', 'Σκούπες'),
    ('4Β0000', 'HAA', 'Σκούπες - Σίδερα - Πιστολάκια - Καφετιέρες'),
    ('5Ι1200', 'DTK', 'Ανιχνευτές καπνού Μη Ραδιενεργοί'),
    ('5Ι1100', 'RDT', 'Ανιχνευτές καπνού Ραδιενεργοί'),
    ('109993', 'HRD', 'Ραδιενεργά, μολυσματικά, σφαίρες'),
    ('109991', 'GCY', 'Φιάλες με εύφλεκτα υλικά και εκρηκτικές ύλες'),
    ('109992', 'FEX', 'Φιάλες πυροσβεστήρων'),
    ('119999', 'MXG', 'Διάφορα σκουπίδια (χώμα, πέτρες, χαρτιά)'),
]
MATERIAL_GROUPS = [
    ('E-Scrap', 'EAR'), ('Άχρηστα', 'AXR'), ('Εμπορικά', 'EMP'), ('Επικίνδυνα', 'EPK'), ('Καλώδια', 'WRE'),
    ('Μέταλλα', 'MTL'), ('Πλακέτες', 'DKT'), ('Πλαστικά', 'CTC'), ('Συσκευές', 'CYK'),
]
NO_GROUP = ('Χωρίς κατηγορία', 'NCT')
ALLOWED = set("ACDEFGHJKLMNPRTUVWXY0123456789")

APPLY = '--apply' in sys.argv
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    labels = {}
    for _c, code, nm in WEEE: labels.setdefault(code, nm)
    for nm, code in MATERIAL_GROUPS + [NO_GROUP]: labels.setdefault(code, 'Υλικά: ' + nm if code not in labels else labels[code])
    bad = [c for c in labels if len(c) != 3 or not set(c) <= ALLOWED]
    types = {t.short_code for t in db.scalars(select(CollectionMediumType)).all() if t.short_code}
    clash = sorted(set(labels) & types)
    print('κωδικοί περιεχομένου:', len(labels), '| κατηγορίες ΑΗΗΕ:', len(WEEE), '| ομάδες υλικών:', len(MATERIAL_GROUPS) + 1)
    print('άκυροι:', bad, '| ίδιοι με κωδικό τύπου:', clash)
    if bad or clash: sys.exit('ΑΠΟΡΡΙΠΤΕΤΑΙ')
    if not APPLY:
        print('(έλεγχος μόνο — πρόσθεσε --apply)'); sys.exit(0)
    for code, label in labels.items():
        row = db.get(ContentCode, code)
        if row: row.label = label
        else: db.add(ContentCode(code=code, label=label, source='SEED'))
    db.flush()
    for off, code, _nm in WEEE:
        row = db.get(ContentCodeMap, ('WEEE', off))
        if row: row.code = code
        else: db.add(ContentCodeMap(kind='WEEE', key=off, code=code))
    for nm, code in MATERIAL_GROUPS + [NO_GROUP]:
        row = db.get(ContentCodeMap, ('SGROUP', nm))
        if row: row.code = code
        else: db.add(ContentCodeMap(kind='SGROUP', key=nm, code=code))
    db.commit()
    print('Εφαρμόστηκαν.')
