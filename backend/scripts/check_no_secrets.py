"""Έλεγχος που ΑΡΝΕΙΤΑΙ commit/push αρχείων με βάση δεδομένων (.db), μυστικά (.env, κλειδιά, keystore), κρυπτογραφημένα αντίγραφα (.wbk) ή πολύ μεγάλα αρχεία.
Καλείται από τα hooks του git (backend/scripts/git_hooks):
   pre-commit : python check_no_secrets.py --staged
   pre-push   : python check_no_secrets.py --range ΑΠΟ..ΩΣ
Κωδικός εξόδου: 0 = ΟΚ, 1 = ΑΠΑΓΟΡΕΥΤΗΚΕ (το commit/push σταματά), 2 = δεν μπόρεσε να τρέξει ο έλεγχος (το hook ΑΦΗΝΕΙ να περάσει, δεν σπάει τη δουλειά)."""
import re, subprocess, sys

BAD = [
    (re.compile(r"\.(db|sqlite3?|db-wal|db-shm|db-journal)$", re.I), "βάση δεδομένων"),
    (re.compile(r"(^|/)\.env$", re.I), "αρχείο μυστικών .env"),
    (re.compile(r"\.(pem|p12|pfx|jks|keystore)$", re.I), "κλειδί/πιστοποιητικό"),
    (re.compile(r"(^|/)backup_private_key\.enc$|\.wbk$", re.I), "κλειδωμένο ιδιωτικό κλειδί ή κρυπτογραφημένο αντίγραφο"),
    (re.compile(r"(^|/)(electrocycle_profile|backups)/", re.I), "προφίλ browser / αντίγραφα"),
]
MAX_MB = 20


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, timeout=60)


def files_staged():
    r = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    out = [f for f in r.stdout.split("\0") if f]
    sizes = {}
    for f in out:
        s = git("cat-file", "-s", ":" + f)
        sizes[f] = int(s.stdout.strip() or 0) if s.returncode == 0 else 0
    return out, sizes


def files_range(rng):
    r = git("diff", "--name-only", "--diff-filter=ACMR", "-z", rng)
    out = [f for f in r.stdout.split("\0") if f]
    sizes = {}
    end = rng.split("..")[-1]
    for f in out:
        s = git("cat-file", "-s", end + ":" + f)
        sizes[f] = int(s.stdout.strip() or 0) if s.returncode == 0 else 0
    return out, sizes


def main(argv):
    try:
        if argv[:1] == ["--staged"]:
            files, sizes = files_staged()
        elif argv[:1] == ["--range"] and len(argv) > 1:
            files, sizes = files_range(argv[1])
        else:
            print(__doc__); return 2
    except Exception as e:
        print("(check_no_secrets: δεν έτρεξε ο έλεγχος:", e, ")"); return 2
    bad = []
    for f in files:
        for rx, why in BAD:
            if rx.search(f.replace("\\", "/")):
                bad.append(f"{f}  ← {why}")
                break
        else:
            if sizes.get(f, 0) > MAX_MB * 1024 * 1024:
                bad.append(f"{f}  ← πολύ μεγάλο αρχείο ({sizes[f] // 2**20} MB)")
    if bad:
        print("\n*** ΑΠΑΓΟΡΕΥΤΗΚΕ: τα παρακάτω αρχεία ΔΕΝ πρέπει να μπουν στο git/GitHub:")
        for b in bad:
            print("   -", b)
        print("Βγάλε τα από το commit (git restore --staged ΑΡΧΕΙΟ). Η βάση και τα μυστικά δεν ανεβαίνουν ποτέ στο GitHub.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
