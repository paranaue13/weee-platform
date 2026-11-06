"""Κρυπτογράφηση αντιγράφων ασφαλείας (μόνο για τα αρχεία που πάνε στο OneDrive και για το .env στο USB).

Πώς δουλεύει (ώστε το καθημερινό πρόγραμμα να ΜΗΝ χρειάζεται κωδικό και ο κωδικός να μη γράφεται πουθενά):
 - Μία φορά φτιάχνεται ζευγάρι κλειδιών (X25519). Το ΔΗΜΟΣΙΟ κλειδί (backup_public.key) δεν είναι μυστικό: με αυτό το πρόγραμμα
   κρυπτογραφεί κάθε βράδυ. Το ΙΔΙΩΤΙΚΟ κλειδί αποθηκεύεται ΜΟΝΟ κλειδωμένο με τον κωδικό σου (backup_private_key.enc, scrypt + AES-256-GCM).
 - Για να ανοίξεις ένα κρυπτογραφημένο αρχείο (.wbk) χρειάζεσαι ΤΟ ΑΡΧΕΙΟ backup_private_key.enc ΚΑΙ τον κωδικό σου (restore_backup.py).
 - Κάθε αρχείο: MAGIC + προσωρινό δημόσιο κλειδί (32 bytes) + nonce (12) + AES-256-GCM(δεδομένα).
Απαιτεί: pip install cryptography"""
import base64, json, os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

MAGIC = b"WEEEBK1\n"
KEY_AAD = b"WEEEKEY1"
PUB_NAME = "backup_public.key"
PRIV_NAME = "backup_private_key.enc"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 16, 8, 1


def _kdf(passphrase: str, salt: bytes, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def generate_keypair(passphrase: str, out_dir: Path) -> None:
    """Φτιάχνει backup_public.key (ανοιχτό) και backup_private_key.enc (κλειδωμένο με τον κωδικό). Δεν γράφει τον κωδικό πουθενά."""
    if len(passphrase) < 10:
        raise ValueError("Ο κωδικός πρέπει να έχει τουλάχιστον 10 χαρακτήρες")
    out_dir.mkdir(parents=True, exist_ok=True)
    priv = X25519PrivateKey.generate()
    raw_priv = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(passphrase, salt)).encrypt(nonce, raw_priv, KEY_AAD)
    (out_dir / PUB_NAME).write_text(base64.b64encode(raw_pub).decode("ascii"), encoding="ascii")
    (out_dir / PRIV_NAME).write_text(json.dumps({"v": 1, "kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
                                                  "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
                                                  "ct": base64.b64encode(ct).decode()}), encoding="utf-8")


def load_public(path: Path) -> bytes:
    raw = base64.b64decode(path.read_text(encoding="ascii").strip())
    if len(raw) != 32:
        raise ValueError("Μη έγκυρο δημόσιο κλειδί")
    return raw


def load_private(path: Path, passphrase: str) -> bytes:
    d = json.loads(path.read_text(encoding="utf-8"))
    key = _kdf(passphrase, base64.b64decode(d["salt"]), d["n"], d["r"], d["p"])
    try:
        return AESGCM(key).decrypt(base64.b64decode(d["nonce"]), base64.b64decode(d["ct"]), KEY_AAD)
    except Exception:
        raise ValueError("Λάθος κωδικός ή κατεστραμμένο αρχείο κλειδιού")


def _derive(shared: bytes, eph_pub: bytes, rcpt_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"weee-backup-v1").derive(shared + eph_pub + rcpt_pub)


def encrypt_file(src: Path, dst: Path, public_raw: bytes) -> None:
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key = _derive(eph.exchange(X25519PublicKey.from_public_bytes(public_raw)), eph_pub, public_raw)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, Path(src).read_bytes(), MAGIC)
    Path(dst).write_bytes(MAGIC + eph_pub + nonce + ct)


def decrypt_file(src: Path, dst: Path, private_raw: bytes) -> None:
    b = Path(src).read_bytes()
    if not b.startswith(MAGIC) or len(b) < len(MAGIC) + 44:
        raise ValueError("Το αρχείο δεν είναι κρυπτογραφημένο αντίγραφο WEEE (.wbk)")
    o = len(MAGIC)
    eph_pub, nonce, ct = b[o:o + 32], b[o + 32:o + 44], b[o + 44:]
    priv = X25519PrivateKey.from_private_bytes(private_raw)
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key = _derive(priv.exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, pub)
    Path(dst).write_bytes(AESGCM(key).decrypt(nonce, ct, MAGIC))
