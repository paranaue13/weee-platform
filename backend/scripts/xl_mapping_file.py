"""Ανάγνωση του αρχείου αντιστοιχίσεων (antistoixisi_apotelesma.txt) και επίλυση σε υλικά/κωδικούς ΑΗΗΕ της βάσης.
Κοινό για τον έλεγχο, την αποθήκευση της αντιστοίχισης και την προεπισκόπηση εισαγωγής."""
import re, sqlite3, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.mat_warehouse import _fold_key

TABS = {'Αξιοποιήσιμα Υλικά': ('EXCEL', 'AXIOPOIISIMA'), 'Υλικά Ειδικής Διαχείρισης': ('EXCEL', 'EIDIKIS_DIACHEIRISIS'), 'Πλακέτες': ('EXCEL', 'PLAKETES'),
        'Υλικά προς Απόρριψη': ('EXCEL', 'APORRIPSI'), 'Πρέσα': ('PRESS', 'PRESS'), 'Εμπορικά': ('COMMERCIAL', 'COMMERCIAL')}
LINE = re.compile(r'^\[(?P<tab>[^\]]+)\]\s+(?P<label>.+?)\s+→\s+(?P<what>.+)$')


def parse(path):
    out = []
    for n, raw in enumerate(open(path, encoding='utf-8').read().splitlines(), 1):
        m = LINE.match(raw.strip())
        if not m:
            continue
        tab, label, what = m['tab'], m['label'].strip(), m['what'].strip()
        r = {'line': n, 'tab': tab, 'label': label, 'what': what}
        if what.startswith('ΥΠΟΚΑΤΗΓΟΡΙΑ ΥΠΟ ΟΜΠΡΕΛΑ'):
            r['kind'] = 'BULK_SUB'; r['erp'], r['name'] = [x.strip() for x in what.replace('ΥΠΟΚΑΤΗΓΟΡΙΑ ΥΠΟ ΟΜΠΡΕΛΑ', '').split('·', 1)]
        elif what.startswith('ΑΠΟ ΠΑΡΑΛΑΒΕΣ'):
            r['kind'] = 'RECEIPTS'; code = what.split('ΑΗΗΕ', 1)[1].strip(); r['weee'], r['name'] = [x.strip() for x in code.split('·', 1)]
        elif what.startswith('ΑΘΡΟΙΣΜΑ/ΕΤΙΚΕΤΑ'):
            r['kind'] = 'SUM'; r['group'] = re.search(r'«(.+)»', what)[1]
        elif what.startswith('ΔΕΝ ΕΙΝΑΙ ΥΛΙΚΟ'):
            r['kind'] = 'NONE'
        elif what.startswith('ΥΛΙΚΟ'):
            r['kind'] = 'MATERIAL'; r['inactive_note'] = '(ανενεργό)' in what
            r['erp'], r['name'] = [x.strip() for x in what.replace('ΥΛΙΚΟ', '', 1).replace('(ανενεργό)', '').split('·', 1)]
        else:
            r['kind'] = '?'
        out.append(r)
    return out


def resolve(db, rows):
    """Προσθέτει material_id / weee_category_id. Επιστρέφει λίστα προβλημάτων."""
    problems = []
    mats = db.execute('select id, galaxy_code, official_description, internal_name, active, is_commercial from materials').fetchall()
    by_erp = {}
    for m in mats:
        by_erp.setdefault(_fold_key(m[1] or ''), []).append(m)
    weee = {_fold_key(c): (i, d) for i, c, d in db.execute('select id, code, description_el from weee_categories')}
    for r in rows:
        if r['kind'] in ('MATERIAL', 'BULK_SUB'):
            c = by_erp.get(_fold_key(r['erp']), [])
            if len(c) != 1:
                problems.append((r['line'], r['tab'], r['label'], f"ο κωδικός ERP «{r['erp']}» " + ('δεν υπάρχει στα μητρώα' if not c else f'υπάρχει {len(c)} φορές')))
                continue
            m = c[0]; r['material_id'] = m[0]; r['mat_active'] = bool(m[4]); r['mat_commercial'] = bool(m[5])
            nm = m[2] or m[3] or ''
            if _fold_key(nm) != _fold_key(r['name']):
                problems.append((r['line'], r['tab'], r['label'], f"το όνομα στο αρχείο «{r['name']}» διαφέρει από το μητρώο «{nm}» (ο ERP {r['erp']} εφαρμόζεται κανονικά)"))
            if r['kind'] == 'MATERIAL' and r['mat_active'] == r.get('inactive_note'):
                problems.append((r['line'], r['tab'], r['label'], f"κατάσταση υλικού: αρχείο {'ανενεργό' if r['inactive_note'] else 'ενεργό'} / μητρώο {'ενεργό' if r['mat_active'] else 'ανενεργό'}"))
            if r['tab'] == 'Εμπορικά' and not r['mat_commercial']:
                problems.append((r['line'], r['tab'], r['label'], f"το υλικό {r['erp']} δεν έχει το τσεκ «Εμπορικό υλικό»"))
            if r['tab'] != 'Εμπορικά' and r['mat_commercial']:
                problems.append((r['line'], r['tab'], r['label'], f"το υλικό {r['erp']} είναι εμπορικό αλλά η καρτέλα δεν είναι «Εμπορικά»"))
        elif r['kind'] == 'RECEIPTS':
            w = weee.get(_fold_key(r['weee']))
            if not w: problems.append((r['line'], r['tab'], r['label'], f"ο κωδικός ΑΗΗΕ «{r['weee']}» δεν υπάρχει"))
            else: r['weee_category_id'] = w[0]
    # ίδια ετικέτα (ίδια πηγή) με δύο διαφορετικούς στόχους
    seen = {}
    for r in rows:
        src = TABS[r['tab']][0]; k = (src, _fold_key(r['label']))
        tgt = (r['kind'], r.get('material_id') or r.get('weee_category_id') or r.get('group'))
        if k in seen and seen[k][1] != tgt:
            problems.append((r['line'], r['tab'], r['label'], f"η ίδια ετικέτα έχει δύο διαφορετικούς στόχους (γραμμές {seen[k][0]} και {r['line']})"))
        seen.setdefault(k, (r['line'], tgt))
    return problems
