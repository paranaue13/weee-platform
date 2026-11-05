"""Έλεγχος: δεν έμεινε γραμμένη λίστα καρτελών Υλικών (κωδικοί ή ονόματα) στον κώδικα.
Οι καρτέλες ορίζονται ΜΟΝΟ στον πίνακα material_tabs (σπόρος: SYSTEM_TABS στο mat_warehouse.py). Κάθε γραμμή με 2+ από τους 4 κωδικούς/ονόματα συστήματος
πρέπει να είναι σε μία από τις γνωστές εξαιρέσεις παρακάτω (σπόρος, φύλλα Excel προέλευσης, ομάδες προέλευσης παραγωγής, αρχική κατάσταση πριν φορτώσει ο πίνακας).
Μόνο ανάγνωση. Χρήση: python check_tab_codes.py"""
import os, re, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app')
CODES = ['AXIOPOIISIMA', 'EIDIKIS_DIACHEIRISIS', 'APORRIPSI', 'PLAKETES']
NAMES = ['Αξιοποιήσιμα Υλικά', 'Υλικά Ειδικής Διαχείρισης', 'Υλικά προς Απόρριψη']
FILES = ['main.py', 'mat_warehouse.py', 'mat_labels.py', 'excel_labels_tool.py', 'models.py', 'static/desktop_v11.html', 'static/mobile_v12.html']
# (αρχείο, απόσπασμα που πρέπει να υπάρχει στη γραμμή) → λόγος
ALLOWED = [
    ('mat_warehouse.py', 'SYSTEM_TABS', 'σπόρος του πίνακα material_tabs (οι 4 καρτέλες-σύστημα)'),
    ('mat_warehouse.py', 'LABEL_GROUP_TAB', 'ομάδα ετικέτας → καρτέλα συστήματος (κανόνας Προφίλ Υλικού)'),
    ('mat_labels.py', '"EIDIKIS_DIACHEIRISIS" if', 'ειδικός κανόνας Πλακετών: οι Πλακέτες είναι ομάδα Ειδικής Διαχείρισης στα δεδομένα'),
    ('excel_labels_tool.py', 'SHEETS', 'φύλλα Excel προέλευσης (όχι καρτέλες)'),
    ('static/desktop_v11.html', 'MAT_GROUP_LABELS', 'ομάδες ΠΡΟΕΛΕΥΣΗΣ Excel στην Παραγωγή (δεν είναι καρτέλες)'),
    ('static/desktop_v11.html', 'MAT_GROUP_ORDER', 'ομάδες ΠΡΟΕΛΕΥΣΗΣ Excel στην Παραγωγή (δεν είναι καρτέλες)'),
    ('static/desktop_v11.html', 'LGROUP_TAB', 'ομάδα ετικέτας → καρτέλα συστήματος'),
    ('static/desktop_v11.html', 'LM_TABS=', 'αρχική κατάσταση πριν φορτώσει ο πίνακας· συμπληρώνεται από το syncLmTabs'),
    ('static/desktop_v11.html', 'LM_TABNAME=', 'αρχική κατάσταση πριν φορτώσει ο πίνακας'),
    ('static/desktop_v11.html', 'data-readygroup', 'κουμπιά καρτελών συστήματος· οι καρτέλες χρήστη φτιάχνονται από τον πίνακα'),
    ('static/desktop_v11.html', 'readyState={', 'αρχική καρτέλα'),
    ('static/desktop_v11.html', 'PLAKETES_LABELS', 'ετικέτες Πλακετών (ειδικός κανόνας Πλακετών)'),
    ('static/desktop_v11.html', 'isPlaketes', 'ειδικός κανόνας Πλακετών'),
    ('static/desktop_v11.html', 'effGroup(label,rawGroup)', 'δίχτυ ασφαλείας: άγνωστη ομάδα → Αξιοποιήσιμα'),
    ('static/desktop_v11.html', 'row.querySelectorAll', 'readyRenderTabs'),
    ('static/desktop_v11.html', '_extra', 'ειδικός κανόνας Πλακετών'),
    ('static/desktop_v11.html', 'writeGroup', 'ειδικός κανόνας Πλακετών'),
    ('static/desktop_v11.html', "b.dataset.readygroup==='PRESS'", 'κουμπιά που δεν δέχονται σύρσιμο (Πρέσα/Πλακέτες/Αποθήκη/Εμπορικά)'),
    ('static/desktop_v11.html', 'readyRenderTabs', 'δίχτυ ασφαλείας ενεργής καρτέλας'),
]
SKIP_FILE_PARTS = ('BROKEN',)


def hits(line):
    n = sum(1 for c in CODES if c in line) + sum(1 for t in NAMES if t in line)
    return n


def main():
    probs = []
    for f in FILES:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        for i, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
            if hits(line) < 2:
                continue
            if any(f == af and frag in line for af, frag, why in ALLOWED):
                continue
            probs.append(f'{f}:{i}: γραμμή με 2+ καρτέλες γραμμένες στον κώδικα → {line.strip()[:160]}')
    for m in probs:
        print(m)
    print('ΠΡΟΒΛΗΜΑΤΑ ΓΡΑΜΜΕΝΩΝ ΛΙΣΤΩΝ ΚΑΡΤΕΛΩΝ:', len(probs))
    return len(probs)


if __name__ == '__main__':
    main()
