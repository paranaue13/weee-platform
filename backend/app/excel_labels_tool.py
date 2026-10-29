"""ΠΡΟΣΩΡΙΝΟ εργαλείο «Εισαγωγή από Excel»: διαβάζει (ΜΟΝΟ ΓΙΑ ΑΝΑΓΝΩΣΗ) τα μηνιαία Excel Υλικών/Πρέσας και επιστρέφει ποιες ετικέτες-στήλες υπάρχουν,
σε ποια καρτέλα και σε ποιους μήνες, ώστε ο χρήστης να τις αντιστοιχίσει σε υλικά των Μητρώων. Δεν γράφει τίποτα σε Excel ούτε στη βάση.
Διαγράφεται (μαζί με την οθόνη του στα Windows) όταν τελειώσει η εισαγωγή."""
import os, glob, re
from datetime import datetime

DEFAULT_FOLDER = r"C:\Users\paran\Desktop\HER app\Files\Εισερχομενα - επεξεργασμένα 1-8 2026"
# καρτέλα Excel (αρχή ονόματος) → καρτέλα προγράμματος
SHEETS = [("3 (", "AXIOPOIISIMA"), ("4 (", "EIDIKIS_DIACHEIRISIS"), ("5 (", "APORRIPSI"), ("ΥΛΙΚΑ ΑΠΟ ΕΜΠΟΡΙΟ", "COMMERCIAL")]
SKIP = re.compile(r"ΣΥΝΟΛΟ|ΑΠΟΘΕΜΑ|ΗΜΕΡΟΜΗΝΙΑ|ΜΕΡΙΚΟ", re.I)
# Πρέσα (καρτέλα «6 (ΠΡΕΣΑ)»): στήλη κιλών → όνομα στήλης Πρέσας όπως τη γνωρίζει το πρόγραμμα (οι άλλες στήλες είναι σύνολα)
PRESS_KG_COLS = {2: "ΠΛΑΣΤΙΚΟ ΑΣΠΡΟ", 4: "ΠΛΑΣΤΙΚΟ ΜΑΥΡΟ", 6: "ΠΛΑΣΤΙΚΟ ΑΝΑΜΕΙΚΤΟ", 8: "ΒΡΩΜΙΟΥΧΟ ΑΝΑΜΕΙΚΤΟ", 11: "ΣΙΔΗΡΟΣ (ΧΥΜΑ)", 13: "ΣΙΔΗΡΟΣ", 15: "ΣΕΡΠΑΤΙΝΑ",
                  17: "ΧΑΛΚΟΣ", 19: "ΑΛΟΥΜΙΝΙΟ ΜΑΛΑΚΟ", 21: "ΚΑΛΩΔΙΑ", 23: "ΧΑΡΤΙ", 25: "ΝΑΥΛΟΝ", 27: "ΠΟΛΥΟΥΡΕΘΑΝΗ"}
_cache: dict = {}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def scan(folder: str | None = None) -> dict:
    folder = folder or DEFAULT_FOLDER
    files = [f for f in sorted(glob.glob(os.path.join(folder, "*.xlsx"))) if not os.path.basename(f).startswith("~$")]   # όχι τα αρχεία κλειδώματος του Excel
    key = tuple((f, os.path.getmtime(f)) for f in files)
    if _cache.get("key") == key:
        return _cache["val"]
    import openpyxl
    labels: dict = {}
    press: dict = {}
    warnings: list = []
    for f in files:
        fname = os.path.basename(f)
        try:
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        except Exception as e:
            warnings.append(f"{fname}: δεν διαβάστηκε ({e})"); continue
        for sname in wb.sheetnames:
            grp = next((g for pre, g in SHEETS if sname.startswith(pre)), None)
            is_press = sname.startswith("6 (")
            if not grp and not is_press:
                continue
            rows = list(wb[sname].iter_rows(values_only=True))
            first = next((i for i, r in enumerate(rows) if r and isinstance(r[0], datetime)), None)
            if first is None:
                continue
            data = [r for r in rows[first:] if r and isinstance(r[0], datetime)]
            if is_press:
                for c, name in PRESS_KG_COLS.items():
                    cells = [(r[0], _num(r[c])) for r in data if c < len(r) and _num(r[c]) != 0]
                    e = press.setdefault(name, {"label": name, "months": set(), "files": set(), "n": 0})
                    e["months"].update(d.strftime("%Y-%m") for d, _ in cells); e["n"] += len(cells)
                    if cells: e["files"].add(fname)
                continue
            hdr_rows = rows[1:first]
            ncol = max(len(r) for r in rows[:first + 1]) if rows else 0
            plak_from = plak_to = None
            for j in range(1, ncol):
                cells = [_clean(r[j]) for r in hdr_rows if j < len(r) and _clean(r[j])]
                if not cells:
                    continue
                lab = cells[-1]
                if sname.startswith("4 (") and cells[0] == "ΠΛΑΚΕΤΕΣ" and len(cells) > 1:
                    pass
                if not lab or SKIP.search(lab):
                    continue
                vals = [(r[0], _num(r[j])) for r in data if j < len(r) and _num(r[j]) != 0]
                is_plak = sname.startswith("4 (") and len(cells) > 1 and cells[0] == "ΠΛΑΚΕΤΕΣ"
                e = labels.setdefault(lab, {"label": lab, "sheets": {}, "months": set(), "files": set(), "n": 0, "plaketes": False})
                s = e["sheets"].setdefault(grp, {"months": set(), "n": 0}); e["plaketes"] = e["plaketes"] or is_plak
                ms = {d.strftime("%Y-%m") for d, _ in vals}
                s["months"].update(ms); s["n"] += len(vals); e["months"].update(ms); e["n"] += len(vals)
                if vals: e["files"].add(fname)
    out = {
        "folder": folder, "files": [os.path.basename(f) for f in files], "warnings": warnings,
        "labels": [{"label": e["label"], "sheets": {g: {"months": sorted(s["months"]), "n": s["n"]} for g, s in e["sheets"].items()}, "months": sorted(e["months"]), "n": e["n"], "plaketes": e["plaketes"], "files": len(e["files"])} for e in labels.values()],
        "press": [{"label": e["label"], "months": sorted(e["months"]), "n": e["n"], "files": len(e["files"])} for e in press.values()],
    }
    _cache["key"] = key; _cache["val"] = out
    return out
