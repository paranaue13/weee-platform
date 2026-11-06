"""Επαναφορά αντιγράφων ασφαλείας σε ΦΑΚΕΛΟ της επιλογής σου (ποτέ πάνω στη ζωντανή βάση).

Χρήση (σε τερματικό, από οποιονδήποτε φάκελο):
  python restore_backup.py ΑΡΧΕΙΟ_ΑΝΤΙΓΡΑΦΟΥ ΦΑΚΕΛΟΣ_ΠΡΟΟΡΙΣΜΟΥ [--key backup_private_key.enc]

ΑΡΧΕΙΟ_ΑΝΤΙΓΡΑΦΟΥ: weee_db_*.zip (USB) ή weee_db_*.zip.wbk (OneDrive), docs_*.zip(.wbk), env_*.wbk
Τα .wbk ζητούν τον κωδικό (κρυφό πεδίο). Μετά από την επαναφορά της βάσης γίνεται έλεγχος ακεραιότητας και φαίνονται τα πλήθη εγγραφών.
Απαιτεί Python 3 και (μόνο για .wbk) το πακέτο cryptography:  pip install cryptography"""
import argparse, getpass, os, sqlite3, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("dest")
    ap.add_argument("--key", default=None, help="το αρχείο backup_private_key.enc (αν λείπει, ψάχνεται δίπλα στο αντίγραφο ή εδώ)")
    ap.add_argument("--password", default=None, help="μόνο για αυτόματες δοκιμές· κανονικά πληκτρολογείται κρυφά")
    a = ap.parse_args(argv)
    src, dest = Path(a.src), Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".wbk":
        import backup_crypto as bc
        key = Path(a.key) if a.key else next((p for p in [src.parent / bc.PRIV_NAME, src.parent.parent / "keys" / bc.PRIV_NAME, HERE / bc.PRIV_NAME, Path.cwd() / bc.PRIV_NAME] if p.exists()), None)
        if not key or not key.exists():
            print("Δεν βρέθηκε το αρχείο backup_private_key.enc. Δώσε το με --key ΔΙΑΔΡΟΜΗ"); return 2
        pw = a.password if a.password is not None else getpass.getpass("Κωδικός κρυπτογράφησης: ")
        priv = bc.load_private(key, pw)
        plain = dest / src.name[:-4]
        bc.decrypt_file(src, plain, priv)
        print("Αποκρυπτογραφήθηκε:", plain)
        src = plain
    out = src
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            bad = z.testzip()
            if bad:
                print("ΠΡΟΣΟΧΗ: κατεστραμμένο αρχείο μέσα στο zip:", bad); return 3
            z.extractall(dest)
            print("Αποσυμπιέστηκε στο:", dest, "->", ", ".join(z.namelist()[:8]))
            dbs = [n for n in z.namelist() if n.lower().endswith(".db")]
        if dbs:
            out = dest / dbs[0]
    if out.suffix.lower() == ".db":
        c = sqlite3.connect(str(out))
        ok = c.execute("pragma integrity_check").fetchone()[0]
        print("Έλεγχος ακεραιότητας βάσης:", ok)
        for t in ("materials", "inbound_loads", "material_output_entries", "material_shipment_entries", "audit_events", "users"):
            try:
                print(f"  {t}: {c.execute(f'select count(*) from {t}').fetchone()[0]}")
            except Exception:
                pass
        c.close()
        return 0 if ok == "ok" else 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
