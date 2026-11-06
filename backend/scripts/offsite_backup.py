"""ΚΑΘΗΜΕΡΙΝΟ αντίγραφο ασφαλείας ΕΚΤΟΣ ΔΙΣΚΟΥ: βάση + κώδικας (+ φωτογραφίες/πρότυπα, εβδομαδιαία τα αρχικά Excel, .env κρυπτογραφημένο).

Προορισμοί: USB με όνομα WEEE-BACKUP (βρίσκεται από το ΟΝΟΜΑ, όχι από το γράμμα) και φάκελος OneDrive. Ποτέ το M: (server εταιρείας).
Τρέχει από την εργασία «WEEE Platform Offsite Backup» (κάθε μέρα 21:30, ή μόλις ανοίξει ο υπολογιστής αν ήταν σβηστός).
 - Η βάση παίρνεται ΜΟΝΟ με το backup API της SQLite (ποτέ απλή αντιγραφή), ελέγχεται (integrity_check) και μετριούνται οι εγγραφές.
 - USB: βάση σε zip (μη κρυπτογραφημένη), πακέτο κώδικα (git bundle), φωτογραφίες/πρότυπα, .env ΚΡΥΠΤΟΓΡΑΦΗΜΕΝΟ, αρχικά Excel (1 φορά/εβδομάδα).
 - OneDrive: βάση και φωτογραφίες ΚΡΥΠΤΟΓΡΑΦΗΜΕΝΕΣ (.wbk, με δημόσιο κλειδί· χωρίς κωδικό στον υπολογιστή), πακέτο κώδικα όπως είναι.
 - Κράτηση (μόνο στα δικά μας αρχεία): 14 ημερήσια + 12 εβδομαδιαία + 12 μηνιαία.
 - Ανέβασμα κώδικα στο GitHub (ιδιωτικό αποθετήριο) αν έχει οριστεί remote «origin» (χωρίς ερώτηση κωδικού· αν δεν είναι συνδεδεμένο, γράφεται στην κατάσταση).
 - Κατάσταση: %LOCALAPPDATA%\\WEEE Platform\\backup_status.json + αρχείο «ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ - ΚΑΤΑΣΤΑΣΗ.txt» στην Επιφάνεια Εργασίας.
Δοκιμές/παράμετροι: --usb-root --onedrive-root --db --local-dir --desktop --excel-dir --no-git"""
import argparse, ctypes, hashlib, json, os, re, shutil, sqlite3, string, subprocess, sys, time, traceback, zipfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE))
LABEL = "WEEE-BACKUP"
FOLDER = "WEEE-Backups"
STATUS_TXT = "ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ - ΚΑΤΑΣΤΑΣΗ.txt"
GUIDE_SRC = PROJECT / "docs" / "ΟΔΗΓΙΕΣ ΕΠΑΝΑΦΟΡΑΣ.txt"
GUIDE_NAME = "ΟΔΗΓΙΕΣ ΕΠΑΝΑΦΟΡΑΣ.txt"
KEEP_DAILY, KEEP_WEEKLY, KEEP_MONTHLY = 14, 12, 12


def iso(d=None):
    return (d or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


class Ctx:
    pass


def log(c, msg):
    line = f"{iso()}  {msg}"
    try:
        c.local.mkdir(parents=True, exist_ok=True)
        with open(c.local / "offsite_backup.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


# ------------------------------------------------------------------ εύρεση προορισμών
def find_usb(label=LABEL):
    """Το USB βρίσκεται από το ΟΝΟΜΑ του (ετικέτα τόμου), όχι από το γράμμα. Δίσκοι δικτύου (π.χ. M:) δεν εξετάζονται ποτέ."""
    if os.name != "nt":
        return None
    k = ctypes.windll.kernel32
    for L in string.ascii_uppercase:
        root = f"{L}:\\"
        if k.GetDriveTypeW(root) in (2, 3):         # 2 = αφαιρούμενος, 3 = σταθερός (USB δίσκοι)· ΟΧΙ 4 = δίκτυο
            buf = ctypes.create_unicode_buffer(261)
            if k.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0) and buf.value.strip().upper() == label.upper():
                return Path(root)
    return None


def find_onedrive():
    p = os.environ.get("OneDriveConsumer") or os.environ.get("OneDrive")
    if p and Path(p).exists():
        return Path(p)
    q = Path.home() / "OneDrive"
    return q if q.exists() else None


def onedrive_running():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OneDrive.exe", "/NH"], capture_output=True, text=True, timeout=20)
        return "onedrive.exe" in r.stdout.lower()
    except Exception:
        return False


# ------------------------------------------------------------------ βοηθητικά αρχεία
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def snapshot_db(db: Path, dest: Path, max_seconds=240.0):
    """Αντίγραφο της ζωντανής βάσης ΜΟΝΟ με το backup API της SQLite + έλεγχος ακεραιότητας + πλήθη εγγραφών."""
    src = sqlite3.connect(str(db), timeout=30)
    dst = sqlite3.connect(str(dest))
    t0 = time.time(); ok = False

    def progress(status, remaining, total):
        if time.time() - t0 > max_seconds:
            raise TimeoutError("η βάση είναι κλειδωμένη")
    try:
        src.backup(dst, pages=2000, progress=progress, sleep=0.25)
        ok = True
    finally:
        dst.close(); src.close()
        if not ok:
            dest.unlink(missing_ok=True)
    c = sqlite3.connect(str(dest))
    try:
        res = c.execute("pragma integrity_check").fetchone()[0]
        counts = {}
        for t in ("materials", "inbound_loads", "material_output_entries", "material_shipment_entries", "ready_material_lots", "audit_events", "users"):
            try:
                counts[t] = c.execute(f"select count(*) from {t}").fetchone()[0]
            except Exception:
                pass
        docs_dir = None
        try:
            r = c.execute("select value from app_settings where key='app.docs_dir'").fetchone()
            docs_dir = (r[0] or "").strip() if r else None
        except Exception:
            pass
    finally:
        c.close()
    if res != "ok":
        raise RuntimeError("ο έλεγχος ακεραιότητας του αντιγράφου απέτυχε: " + str(res)[:80])
    return counts, docs_dir


def zip_files(items, out: Path, level=6):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as z:
        for src, arc in items:
            z.write(src, arc)
    with zipfile.ZipFile(out) as z:
        if z.testzip():
            raise RuntimeError("το zip είναι κατεστραμμένο")


def zip_tree(root: Path, out: Path, prefix="", level=6, skip=()):
    with zipfile.ZipFile(out, "a" if out.exists() else "w", zipfile.ZIP_DEFLATED, compresslevel=level) as z:
        for p in root.rglob("*"):
            if p.is_file() and not any(s in p.parts for s in skip):
                try:
                    z.write(p, str(Path(prefix) / p.relative_to(root)))
                except (PermissionError, OSError):
                    pass


def put(src: Path, dst_dir: Path, name=None, sidecar=False) -> Path:
    """Αντιγραφή με προσωρινό όνομα, έλεγχος SHA256 μετά την αντιγραφή και μετά μετονομασία (ποτέ μισό αρχείο με το τελικό όνομα)."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    final = dst_dir / (name or src.name)
    part = dst_dir / (final.name + ".part")
    shutil.copyfile(src, part)
    want = sha256(src)
    if sha256(part) != want or part.stat().st_size != src.stat().st_size:
        part.unlink(missing_ok=True)
        raise RuntimeError("η αντιγραφή δεν ταιριάζει με το πρωτότυπο: " + final.name)
    os.replace(part, final)
    if sidecar:
        (dst_dir / (final.name + ".sha256")).write_text(f"{want}  {final.name}\n", encoding="ascii")
    return final


STAMP_RE = re.compile(r"_(\d{8})_(\d{4})")


def prune(dirpath: Path, prefix: str, daily=KEEP_DAILY, weekly=KEEP_WEEKLY, monthly=KEEP_MONTHLY):
    """Σβήνει ΜΟΝΟ δικά μας αρχεία (prefix_YYYYMMDD_HHMM...) που ξεπέρασαν την κράτηση: 14 ημερήσια, 12 εβδομαδιαία, 12 μηνιαία."""
    if not dirpath.exists():
        return 0
    groups = {}
    for f in dirpath.iterdir():
        if f.is_file() and f.name.startswith(prefix + "_"):
            m = STAMP_RE.search(f.name)
            if m:
                groups.setdefault(m.group(1) + m.group(2), []).append(f)
    stamps = sorted(groups, reverse=True)
    keep, days, weeks, months = set(), set(), set(), set()
    for s in stamps:
        d = datetime.strptime(s[:8], "%Y%m%d").date()
        if d not in days and len(days) < daily:
            days.add(d); keep.add(s)
        w = d.isocalendar()[:2]
        if w not in weeks and len(weeks) < weekly:
            weeks.add(w); keep.add(s)
        mo = (d.year, d.month)
        if mo not in months and len(months) < monthly:
            months.add(mo); keep.add(s)
    n = 0
    for s in stamps:
        if s not in keep:
            for f in groups[s]:
                try:
                    f.unlink(); n += 1
                except Exception:
                    pass
    return n


def git_exe():
    for c in (shutil.which("git"), r"C:\Program Files\Git\bin\git.exe", r"C:\Program Files\Git\cmd\git.exe"):
        if c and Path(c).exists():
            return c
    return None


def git_run(args, timeout=120, env=None):
    g = git_exe()
    if not g:
        raise RuntimeError("δεν βρέθηκε το git")
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    e.update(env or {})
    return subprocess.run([g] + args, cwd=str(PROJECT), capture_output=True, text=True, timeout=timeout, env=e)


# ------------------------------------------------------------------ κατάσταση
def load_status(c):
    try:
        return json.loads((c.local / "backup_status.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def when(s):
    return s if s else "ΠΟΤΕ"


def render_txt(st):
    L = ["ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ ΕΚΤΟΣ ΔΙΣΚΟΥ - ΚΑΤΑΣΤΑΣΗ", "=" * 52, "", "Τελευταίος έλεγχος: " + when(st.get("last_run"))]
    ext = st.get("last_external_ok")
    L.append("Τελευταίο ΕΠΙΤΥΧΕΣ εξωτερικό αντίγραφο βάσης: " + when(ext))
    try:
        age = (datetime.now() - datetime.strptime(ext, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600 if ext else None
    except Exception:
        age = None
    if age is None or age > 36:
        L += ["", "*** ΠΡΟΣΟΧΗ: ΔΕΝ ΥΠΑΡΧΕΙ ΠΡΟΣΦΑΤΟ ΕΞΩΤΕΡΙΚΟ ΑΝΤΙΓΡΑΦΟ (πάνω από 36 ώρες ή ποτέ). ***"]
    else:
        L += ["", "ΟΛΑ ΕΝΤΑΞΕΙ: υπάρχει εξωτερικό αντίγραφο των τελευταίων 36 ωρών."]
    for key, title in (("usb", "USB «WEEE-BACKUP»"), ("onedrive", "OneDrive"), ("github", "GitHub (κώδικας)")):
        t = st.get(key) or {}
        L += ["", title + ":", "  Τελευταία επιτυχία: " + when(t.get("last_ok")), "  Τελευταίο αποτέλεσμα: " + (t.get("message") or "-")]
    cnt = st.get("db_counts") or {}
    if cnt:
        L += ["", "Εγγραφές στο τελευταίο αντίγραφο: " + ", ".join(f"{k} {v}" for k, v in cnt.items())]
    if st.get("errors"):
        L += ["", "Προβλήματα στην τελευταία εκτέλεση:"] + ["  - " + e for e in st["errors"]]
    L += ["", "Τι κάνω αν δείχνει πρόβλημα:",
          "  • «USB δεν βρέθηκε»: βάλε το USB με όνομα WEEE-BACKUP στον υπολογιστή· θα γίνει αντιγραφή στο επόμενο βράδυ ή τρέξε το «ΑΝΤΙΓΡΑΦΟ ΑΣΦΑΛΕΙΑΣ ΤΩΡΑ.cmd».",
          "  • «λείπει ο κωδικός κρυπτογράφησης»: διπλό κλικ στο «ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP.cmd».",
          "  • «GitHub: δεν έχει συνδεθεί»: διπλό κλικ στο «ΑΝΕΒΑΣΜΑ ΣΤΟ GITHUB.cmd».",
          "  • Για επαναφορά διάβασε το αρχείο «ΟΔΗΓΙΕΣ ΕΠΑΝΑΦΟΡΑΣ.txt».", "",
          "Πού βλέπεις το ✓ του OneDrive: άνοιξε τον φάκελο C:\\Users\\paran\\OneDrive\\WEEE-Backups στον Εξερευνητή αρχείων.",
          "Πράσινο ✓ δίπλα στο αρχείο = ανέβηκε στο cloud· μπλε κύκλος με βελάκια = ανεβαίνει ακόμα."]
    return "\n".join(L) + "\n"


def write_status(c, st):
    c.local.mkdir(parents=True, exist_ok=True)
    (c.local / "backup_status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        c.desktop.mkdir(parents=True, exist_ok=True)
        (c.desktop / STATUS_TXT).write_text(render_txt(st), encoding="utf-8-sig")
    except Exception as e:
        log(c, "δεν γράφτηκε το αρχείο κατάστασης στην Επιφάνεια Εργασίας: " + str(e))


# ------------------------------------------------------------------ κύρια ροή
def sync_support_files(c, root: Path, st_text: str):
    """Οδηγίες επαναφοράς, εργαλεία επαναφοράς, κλειδιά (ανοιχτό + κλειδωμένο ιδιωτικό)· δίπλα στα αντίγραφα."""
    base = root / FOLDER
    base.mkdir(parents=True, exist_ok=True)
    if GUIDE_SRC.exists():
        shutil.copyfile(GUIDE_SRC, base / GUIDE_NAME)
    tools = base / "tools"; tools.mkdir(exist_ok=True)
    for n in ("restore_backup.py", "backup_crypto.py"):
        shutil.copyfile(HERE / n, tools / n)
    keys = base / "keys"
    for n in ("backup_public.key", "backup_private_key.enc"):
        if (c.keys / n).exists():
            keys.mkdir(exist_ok=True)
            shutil.copyfile(c.keys / n, keys / n)
    (base / "backup_status.json").write_text(json.dumps(load_status(c), ensure_ascii=False, indent=1), encoding="utf-8")


def run_target(c, name, root: Path, art, encrypt_pub, usb: bool, st):
    """Γράφει τα αρχεία σε έναν προορισμό. Επιστρέφει (db_ok, μήνυμα)."""
    base = root / FOLDER
    errs = []
    need = sum(p.stat().st_size for p in art.values() if p and p.exists()) * 2 + 200 * 1024 * 1024
    free = shutil.disk_usage(str(root)).free
    if free < need:
        raise RuntimeError(f"δεν υπάρχει αρκετός ελεύθερος χώρος ({free // 2**20} MB ελεύθερα, χρειάζονται ~{need // 2**20} MB)")
    ts = c.stamp
    db_ok = False
    # --- βάση
    if "db_zip" not in art:
        errs.append("ΔΕΝ υπάρχει αντίγραφο βάσης αυτής της εκτέλεσης (δες το αρχείο offsite_backup.log)")
    elif usb:
        put(art["db_zip"], base / "db", f"weee_db_{ts}.zip", sidecar=True); db_ok = True
    elif encrypt_pub is not None:
        from backup_crypto import encrypt_file
        enc = c.tmp / f"weee_db_{ts}.zip.wbk"
        encrypt_file(art["db_zip"], enc, encrypt_pub)
        put(enc, base / "db", enc.name, sidecar=True); db_ok = True
    else:
        errs.append("η βάση ΔΕΝ ανέβηκε στο OneDrive: λείπει η ρύθμιση κωδικού κρυπτογράφησης («ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP.cmd»)")
    # --- κώδικας (όπως είναι· ανεβαίνει και στο GitHub)
    if art.get("bundle"):
        put(art["bundle"], base / "code", f"weee_code_{ts}.bundle", sidecar=True)
    # --- φωτογραφίες/πρότυπα
    if art.get("docs_zip"):
        if usb:
            put(art["docs_zip"], base / "docs", f"docs_{ts}.zip")
        elif encrypt_pub is not None:
            from backup_crypto import encrypt_file
            enc = c.tmp / f"docs_{ts}.zip.wbk"
            encrypt_file(art["docs_zip"], enc, encrypt_pub)
            put(enc, base / "docs", enc.name)
    if usb:
        # .env ΜΟΝΟ στο USB και ΜΟΝΟ κρυπτογραφημένο
        envf = PROJECT / "backend" / ".env"
        if envf.exists():
            if encrypt_pub is not None:
                from backup_crypto import encrypt_file
                enc = c.tmp / f"env_{ts}.wbk"
                encrypt_file(envf, enc, encrypt_pub)
                put(enc, base / "env", enc.name)
            else:
                errs.append("το .env ΔΕΝ αντιγράφηκε: λείπει η ρύθμιση κωδικού κρυπτογράφησης")
        # αρχικά Excel: μία φορά την εβδομάδα
        ex = base / "excel"
        recent = ex.exists() and any(f.stat().st_mtime > time.time() - 7 * 86400 for f in ex.glob("Files_*.zip"))
        if c.excel_dir.exists() and (not recent or c.force_weekly):
            z = c.tmp / f"Files_{ts}.zip"
            zip_tree(c.excel_dir, z, prefix="Files", level=1)
            put(z, ex, z.name)
            prune(ex, "Files", daily=0, weekly=4, monthly=6)
            z.unlink(missing_ok=True)
    # κράτηση: μόνο στα δικά μας αρχεία
    for sub, pre in (("db", "weee_db"), ("code", "weee_code"), ("docs", "docs"), ("env", "env")):
        prune(base / sub, pre)
    sync_support_files(c, root, "")
    return db_ok, ("; ".join(errs) if errs else "ΟΚ")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usb-root"); ap.add_argument("--onedrive-root"); ap.add_argument("--db"); ap.add_argument("--local-dir")
    ap.add_argument("--desktop"); ap.add_argument("--excel-dir"); ap.add_argument("--no-git", action="store_true"); ap.add_argument("--force-weekly", action="store_true")
    ap.add_argument("--keys-dir")
    a = ap.parse_args(argv)
    c = Ctx()
    c.local = Path(a.local_dir) if a.local_dir else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "WEEE Platform"
    c.keys = Path(a.keys_dir) if a.keys_dir else c.local / "backup_keys"
    c.desktop = Path(a.desktop) if a.desktop else Path.home() / "Desktop"
    c.excel_dir = Path(a.excel_dir) if a.excel_dir else PROJECT.parents[1] / "Files"
    c.force_weekly = a.force_weekly
    c.stamp = datetime.now().strftime("%Y%m%d_%H%M")
    c.tmp = c.local / "offsite_tmp"
    db = Path(a.db) if a.db else c.local / "data" / "weee_dev.db"
    st = load_status(c)
    st.setdefault("usb", {}); st.setdefault("onedrive", {}); st.setdefault("github", {})
    st["last_run"] = iso(); st["errors"] = []
    log(c, "=== ΑΡΧΗ αντιγράφου ασφαλείας εκτός δίσκου ===")
    try:
        if c.tmp.exists():
            shutil.rmtree(c.tmp, ignore_errors=True)
        c.tmp.mkdir(parents=True, exist_ok=True)
        art = {}
        ran_ok = False      # επιτυχία ΑΥΤΗΣ της εκτέλεσης (όχι παλιότερης)
        # --- βάση
        try:
            snap = c.tmp / "weee_dev.db"
            counts, docs_dir = snapshot_db(db, snap)
            st["db_counts"] = counts
            z = c.tmp / f"weee_db_{c.stamp}.zip"
            zip_files([(snap, "weee_dev.db")], z)
            art["db_zip"] = z
            log(c, f"βάση ΟΚ: {counts}")
        except Exception as e:
            st["errors"].append("βάση: " + str(e)); log(c, "ΑΠΟΤΥΧΙΑ βάσης: " + traceback.format_exc()); docs_dir = None
        # --- κώδικας
        try:
            b = c.tmp / f"weee_code_{c.stamp}.bundle"
            r = git_run(["bundle", "create", str(b), "--all"], timeout=180)
            if r.returncode != 0 or not b.exists():
                raise RuntimeError((r.stderr or r.stdout or "").strip()[:150])
            v = git_run(["bundle", "verify", str(b)], timeout=120)
            if v.returncode != 0:
                raise RuntimeError("το πακέτο κώδικα δεν πέρασε τον έλεγχο")
            art["bundle"] = b
        except Exception as e:
            st["errors"].append("κώδικας: " + str(e)); log(c, "ΑΠΟΤΥΧΙΑ πακέτου κώδικα: " + str(e))
        # --- φωτογραφίες/αναφορές + πρότυπα αναφορών
        try:
            dz = c.tmp / f"docs_{c.stamp}.zip"
            n = 0
            try:
                sys.path.insert(0, str(PROJECT / "backend"))
                from app import docs_storage
                if docs_dir:
                    docs_storage.set_custom_dir(docs_dir)
                droot = docs_storage.documents_dir() / "WEEE Platform"
            except Exception:
                droot = Path.home() / "Documents" / "WEEE Platform"
            if droot.exists():
                zip_tree(droot, dz, prefix="WEEE Platform"); n += 1
            tpl = c.local / "data" / "report_templates"
            if tpl.exists():
                zip_tree(tpl, dz, prefix="report_templates"); n += 1
            if n:
                art["docs_zip"] = dz
        except Exception as e:
            st["errors"].append("φωτογραφίες/πρότυπα: " + str(e)); log(c, "ΑΠΟΤΥΧΙΑ docs: " + str(e))
        # --- κλειδί κρυπτογράφησης (μόνο δημόσιο)
        pub = None
        try:
            from backup_crypto import PUB_NAME, load_public
            if (c.keys / PUB_NAME).exists():
                pub = load_public(c.keys / PUB_NAME)
        except Exception as e:
            st["errors"].append("κλειδί: " + str(e))
        # --- προορισμοί
        usb = Path(a.usb_root) if a.usb_root else find_usb()
        if usb is None:
            st["usb"]["message"] = "ΔΕΝ ΒΡΕΘΗΚΕ το USB με όνομα WEEE-BACKUP (δεν είναι συνδεδεμένο;)"
        else:
            try:
                ok, msg = run_target(c, "usb", usb, art, pub, True, st)
                if ok:
                    ran_ok = True
                    st["usb"]["last_ok"] = iso()
                st["usb"]["message"] = msg; st["usb"]["path"] = str(usb)
                log(c, f"USB {usb}: {msg}")
            except Exception as e:
                st["usb"]["message"] = "ΑΠΟΤΥΧΙΑ: " + str(e); log(c, "ΑΠΟΤΥΧΙΑ USB: " + traceback.format_exc())
        od = Path(a.onedrive_root) if a.onedrive_root else find_onedrive()
        running = onedrive_running() if not a.onedrive_root else True
        if od is None:
            st["onedrive"]["message"] = "ΔΕΝ ΒΡΕΘΗΚΕ ο φάκελος OneDrive"
        else:
            try:
                ok, msg = run_target(c, "onedrive", od, art, pub, False, st)
                if ok:
                    ran_ok = True
                    st["onedrive"]["last_ok"] = iso()
                if not running:
                    msg += ("; " if msg != "ΟΚ" else "") + "ΠΡΟΣΟΧΗ: το OneDrive δεν τρέχει, δεν θα ανέβουν τα αρχεία στο cloud μέχρι να ανοίξει"
                    msg = msg.replace("ΟΚ; ", "")
                st["onedrive"]["message"] = msg; st["onedrive"]["path"] = str(od); st["onedrive"]["running"] = running
                log(c, f"OneDrive {od}: {msg}")
            except Exception as e:
                st["onedrive"]["message"] = "ΑΠΟΤΥΧΙΑ: " + str(e); log(c, "ΑΠΟΤΥΧΙΑ OneDrive: " + traceback.format_exc())
        # --- GitHub
        if not a.no_git:
            try:
                rem = git_run(["remote", "get-url", "origin"], timeout=20)
                if rem.returncode != 0:
                    st["github"]["message"] = "δεν έχει οριστεί αποθετήριο GitHub"
                else:
                    r = git_run(["push", "origin", "master"], timeout=120)
                    if r.returncode == 0:
                        git_run(["push", "origin", "--tags"], timeout=120)
                        st["github"]["last_ok"] = iso(); st["github"]["message"] = "ΟΚ: ο κώδικας είναι στο GitHub"
                    else:
                        tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["άγνωστο σφάλμα"])[-1][:140]
                        st["github"]["message"] = "ΔΕΝ ανέβηκε (έχεις συνδεθεί στο GitHub; διπλό κλικ στο «ΑΝΕΒΑΣΜΑ ΣΤΟ GITHUB.cmd»): " + tail
                log(c, "GitHub: " + st["github"]["message"])
            except Exception as e:
                st["github"]["message"] = "ΑΠΟΤΥΧΙΑ: " + str(e)[:140]
        # --- σύνοψη
        times = [t for t in (st["usb"].get("last_ok"), st["onedrive"].get("last_ok")) if t]
        st["last_external_ok"] = max(times) if times else st.get("last_external_ok")
        for k, t in (("USB", st["usb"]), ("OneDrive", st["onedrive"])):
            m = t.get("message") or ""
            if m and m != "ΟΚ" and m.startswith(("ΔΕΝ", "ΑΠΟΤΥΧΙΑ", "η βάση ΔΕΝ", "το .env")):
                st["errors"].append(f"{k}: {m}")
        st["last_run_ok"] = ran_ok and not st["errors"]
        return 0 if ran_ok else 1
    except Exception as e:
        st["errors"].append("γενικό σφάλμα: " + str(e)); log(c, traceback.format_exc()); return 1
    finally:
        write_status(c, st)
        shutil.rmtree(c.tmp, ignore_errors=True)
        log(c, "=== ΤΕΛΟΣ ===")


if __name__ == "__main__":
    sys.exit(main())
