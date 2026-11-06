"""Ρύθμιση του κωδικού κρυπτογράφησης των αντιγράφων. ΤΡΕΧΕΙ ΜΕ ΔΙΠΛΟ ΚΛΙΚ στο «ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP.cmd».
Ο κωδικός πληκτρολογείται σε κρυφό πεδίο (δεν φαίνεται όταν γράφεις) δύο φορές και ΔΕΝ γράφεται πουθενά.
Φτιάχνεται ζευγάρι κλειδιών: το ανοιχτό μένει στον υπολογιστή (%LOCALAPPDATA%\\WEEE Platform\\backup_keys), και τα δύο αρχεία
(ανοιχτό + κλειδωμένο) αντιγράφονται στο USB και στο OneDrive την επόμενη αντιγραφή. Χωρίς ΤΟΝ ΚΩΔΙΚΟ δεν ανοίγουν τα κρυπτογραφημένα αντίγραφα· κράτα τον κωδικό σε ασφαλές μέρος (π.χ. γραμμένο σε χαρτί σε συρτάρι)."""
import getpass, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_crypto as bc

LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "WEEE Platform"
KEYS = LOCAL / "backup_keys"


def main() -> int:
    print("=" * 70)
    print(" ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ ΚΡΥΠΤΟΓΡΑΦΗΣΗΣ ΑΝΤΙΓΡΑΦΩΝ ΑΣΦΑΛΕΙΑΣ")
    print("=" * 70)
    if (KEYS / bc.PUB_NAME).exists():
        print("\nΥπάρχει ήδη κωδικός/κλειδιά στον υπολογιστή:", KEYS)
        print("Αν φτιάξεις νέο, τα ΠΑΛΙΑ κρυπτογραφημένα αντίγραφα ΔΕΝ θα ανοίγουν με τον νέο κωδικό.")
        if input("Θες σίγουρα νέο κωδικό; Γράψε NAI για να συνεχίσεις: ").strip().upper() not in ("NAI", "ΝΑΙ"):
            print("Δεν έγινε καμία αλλαγή.")
            return 0
    print("\nΟ κωδικός δεν φαίνεται όταν τον γράφεις (είναι κανονικό). Τουλάχιστον 10 χαρακτήρες.")
    a = getpass.getpass("Νέος κωδικός: ")
    b = getpass.getpass("Ξανά τον ίδιο κωδικό: ")
    if a != b:
        print("\nΟι δύο κωδικοί δεν ταιριάζουν. Δεν έγινε καμία αλλαγή.")
        return 1
    try:
        bc.generate_keypair(a, KEYS)
    except ValueError as e:
        print("\n" + str(e))
        return 1
    print("\nΕΤΟΙΜΟ. Τα κλειδιά αποθηκεύτηκαν στο:", KEYS)
    print("ΜΗΝ ξεχάσεις τον κωδικό: χωρίς αυτόν δεν ανοίγουν τα κρυπτογραφημένα αντίγραφα του OneDrive και το αρχείο .env του USB.")
    # πρώτη πλήρης αντιγραφή αμέσως, ώστε τα κλειδιά να φτάσουν στο USB και στο OneDrive
    try:
        import offsite_backup
        print("\nΓίνεται τώρα η πρώτη πλήρης αντιγραφή...")
        offsite_backup.main([])
    except Exception as e:
        print("Η αντιγραφή θα γίνει το βράδυ στις 21:30 (", e, ")")
    input("\nΠάτα Enter για να κλείσει το παράθυρο...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
