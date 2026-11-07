"""Ρύθμιση του κωδικού κρυπτογράφησης των αντιγράφων. ΤΡΕΧΕΙ ΜΕ ΔΙΠΛΟ ΚΛΙΚ στο «ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP.cmd».
Ο κωδικός πληκτρολογείται σε κρυφό πεδίο (δεν φαίνεται όταν γράφεις) δύο φορές και ΔΕΝ γράφεται πουθενά.
Φτιάχνεται ζευγάρι κλειδιών: το ανοιχτό μένει στον υπολογιστή (%LOCALAPPDATA%/WEEE Platform/backup_keys), και τα δύο αρχεία
(ανοιχτό + κλειδωμένο) αντιγράφονται στο USB και στο OneDrive την επόμενη αντιγραφή. Χωρίς ΤΟΝ ΚΩΔΙΚΟ δεν ανοίγουν τα κρυπτογραφημένα αντίγραφα· κράτα τον κωδικό σε ασφαλές μέρος (π.χ. γραμμένο σε χαρτί σε συρτάρι).
Παράμετροι ΜΟΝΟ για δοκιμές: --keys-dir ΦΑΚΕΛΟΣ, --no-backup, --test-pw ΚΩΔΙΚΟΣ1 ΚΩΔΙΚΟΣ2 (δοκιμαστικοί κωδικοί χωρίς πληκτρολόγηση)."""
import getpass, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_crypto as bc

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "WEEE Platform"
KEYS = LOCAL / "backup_keys"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    keys = KEYS
    no_backup = "--no-backup" in argv
    test_pw = None
    if "--keys-dir" in argv:
        keys = Path(argv[argv.index("--keys-dir") + 1])
    if "--test-pw" in argv:
        i = argv.index("--test-pw"); test_pw = (argv[i + 1], argv[i + 2])
    print("=" * 70)
    print(" ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ ΚΡΥΠΤΟΓΡΑΦΗΣΗΣ ΑΝΤΙΓΡΑΦΩΝ ΑΣΦΑΛΕΙΑΣ")
    print("=" * 70)
    if (keys / bc.PUB_NAME).exists():
        print("\nΥπάρχει ήδη κωδικός/κλειδιά στον υπολογιστή:", keys)
        print("Αν φτιάξεις νέο, τα ΠΑΛΙΑ κρυπτογραφημένα αντίγραφα ΔΕΝ θα ανοίγουν με τον νέο κωδικό.")
        ans = "NAI" if test_pw else input("Θες σίγουρα νέο κωδικό; Γράψε NAI για να συνεχίσεις: ")
        if ans.strip().upper() not in ("NAI", "ΝΑΙ"):
            print("Δεν έγινε καμία αλλαγή.")
            return 0
    print()
    print("ΠΡΙΝ ΓΡΑΨΕΙΣ ΤΟΝ ΚΩΔΙΚΟ, ΔΙΑΒΑΣΕ ΑΥΤΑ:")
    print("  1. Όταν πληκτρολογείς τον κωδικό ΔΕΝ ΘΑ ΦΑΝΕΙ ΤΙΠΟΤΑ στην οθόνη (ούτε τελείες ούτε αστεράκια).")
    print("     Αυτό είναι ΦΥΣΙΟΛΟΓΙΚΟ και γίνεται για την ασφάλειά σου. Γράψε τον κωδικό κανονικά και πάτα Enter.")
    print("  2. Γράψε τον κωδικό με ΑΓΓΛΙΚΟ πληκτρολόγιο (EN), όχι ελληνικό, και τουλάχιστον 10 χαρακτήρες.")
    print("  3. ΚΡΑΤΑ ΤΟΝ ΚΩΔΙΚΟ ΓΡΑΜΜΕΝΟ ΣΕ ΧΑΡΤΙ σε ασφαλές μέρος. Χωρίς αυτόν δεν ανοίγουν τα κρυπτογραφημένα αντίγραφα.")
    print("  4. Θα σου τον ζητήσει ΔΥΟ φορές (η δεύτερη για να βεβαιωθούμε ότι δεν έκανες λάθος).")
    print()
    if test_pw:
        a, b = test_pw
    else:
        a = getpass.getpass("Γράψε τον νέο κωδικό (δεν φαίνεται) και πάτα Enter: ")
        b = getpass.getpass("Γράψε ξανά τον ίδιο κωδικό (δεν φαίνεται) και πάτα Enter: ")
    if a != b:
        print("\n" + "!" * 70)
        print(" Οι δύο κωδικοί δεν ταιριάζουν, ξαναπροσπάθησε.")
        print(" Δεν έγινε καμία αλλαγή. Κλείσε αυτό το παράθυρο και ξανάνοιξε το «ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP».")
        print("!" * 70)
        return 1
    try:
        bc.generate_keypair(a, keys)
    except ValueError as e:
        print("\n" + "!" * 70)
        print(" ΔΕΝ ορίστηκε ο κωδικός: " + str(e))
        print("!" * 70)
        return 1
    print("\n" + "=" * 70)
    print(" Ο κωδικός ορίστηκε.")
    print("=" * 70)
    print("Τα κλειδιά αποθηκεύτηκαν στο:", keys)
    print("ΜΗΝ ξεχάσεις τον κωδικό: χωρίς αυτόν δεν ανοίγουν τα κρυπτογραφημένα αντίγραφα του OneDrive και το αρχείο .env του USB.")
    # πρώτη πλήρης αντιγραφή αμέσως, ώστε τα κλειδιά να φτάσουν στο USB και στο OneDrive
    if not no_backup:
        try:
            import offsite_backup
            print("\nΓίνεται τώρα η πρώτη πλήρης αντιγραφή...")
            offsite_backup.main([])
        except Exception as e:
            print("Η αντιγραφή θα γίνει το βράδυ στις 21:30 (", e, ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
