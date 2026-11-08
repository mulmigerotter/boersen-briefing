"""Verschlüsselt die Inhalte des gesperrten Bereichs (Zeitschriften) mit dem Zugangscode.

    python scripts/lock.py inhalt.json --pin CODE     # verschlüsseln -> docs/data/hefte.enc.json
    python scripts/lock.py --unlock --pin CODE        # Inhalt wieder anzeigen

Der Klartext gehört NICHT ins Repository. Die Webseite entschlüsselt im Browser
(AES-GCM, Schlüssel per PBKDF2-SHA256 aus dem Code). Der Code öffnet die ganze Seite.
Die Börsenkürzel der Empfehlungen landen zusätzlich in watch.json, damit der
tägliche Lauf Kurs und Schwankung dafür holt (docs/data/quotes.json).
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "hefte.enc.json"
WATCH = ROOT / "watch.json"
ITER = 250_000

b64 = lambda b: base64.b64encode(b).decode()


def key(pin, salt, it):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it)
    return kdf.derive(pin.encode())


def lock(src, pin):
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    salt, iv = os.urandom(16), os.urandom(12)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    ct = AESGCM(key(pin, salt, ITER)).encrypt(iv, plain, None)
    OUT.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt),
                               "iv": b64(iv), "ct": b64(ct)}), encoding="utf-8")
    syms = sorted({p["sym"] for i in data["issues"] for p in i["picks"] if p.get("sym")})
    WATCH.write_text(json.dumps({"watch": syms}, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} geschrieben ({len(ct)} Bytes), {len(syms)} Kürzel in watch.json")


def unlock(pin):
    blob = json.loads(OUT.read_text(encoding="utf-8"))
    k = key(pin, base64.b64decode(blob["salt"]), blob["iter"])
    plain = AESGCM(k).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)
    print(json.dumps(json.loads(plain), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?")
    ap.add_argument("--pin", default=os.environ.get("AK_PIN"))
    ap.add_argument("--unlock", action="store_true")
    a = ap.parse_args()
    if not a.pin:
        sys.exit("PIN fehlt (--pin oder AK_PIN)")
    unlock(a.pin) if a.unlock else lock(a.src, a.pin)
