# -*- coding: utf-8 -*-
"""Coffre chiffré côté serveur pour les clés API, tokens et jetons Google.

Chiffrement authentifié (encrypt-then-MAC) avec dérivation PBKDF2-SHA256.
Aucune clé n'est jamais renvoyée au navigateur : seuls des indicateurs
« connecté / non connecté » sont exposés. Le coffre et sa clé doivent rester
hors du dépôt (voir .gitignore) : en production, TUS_VAULT_KEY est un secret.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
# Le dossier du coffre peut être déplacé hors du dépôt avec TUS_VAULT_DIR.
VAULT_DIR = Path(os.environ.get("TUS_VAULT_DIR", "")).expanduser() if os.environ.get("TUS_VAULT_DIR") else BASE
KEY_FILE = VAULT_DIR / ".vault_key"
DATA_FILE = VAULT_DIR / "vault.json"
_LOCK = threading.RLock()
_CACHE = {"signature": None, "data": None}


def _master():
    env = os.environ.get("TUS_VAULT_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip().encode("utf-8")
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48).encode("utf-8")
    KEY_FILE.write_text(key.decode("utf-8"), encoding="utf-8")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def _keys(master, salt):
    material = hashlib.pbkdf2_hmac("sha256", master, salt, 180000, dklen=64)
    return material[:32], material[32:]


def encrypt(text):
    master = _master()
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _keys(master, salt)
    data = str(text).encode("utf-8")
    stream = b""
    counter = 0
    while len(stream) < len(data):
        stream += hmac.new(enc_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(salt + nonce + tag + cipher).decode("ascii")


def decrypt(blob):
    raw = base64.urlsafe_b64decode(str(blob).encode("ascii"))
    if len(raw) < 64:
        raise ValueError("Coffre illisible")
    salt, nonce, tag, cipher = raw[:16], raw[16:32], raw[32:64], raw[64:]
    enc_key, mac_key = _keys(_master(), salt)
    expected = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Coffre illisible ou clé maître incorrecte")
    def _stream(key):
        out = b""
        counter = 0
        while len(out) < len(cipher):
            out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            counter += 1
        return bytes(a ^ b for a, b in zip(cipher, out))

    # Les coffres créés avant la séparation des clés utilisaient mac_key comme
    # keystream. On les relit sans perte en choisissant le déchiffrement dont le
    # JSON est valide ; toute réécriture utilise ensuite enc_key.
    candidates = []
    for key in (enc_key, mac_key):
        try:
            text = _stream(key).decode("utf-8")
        except UnicodeDecodeError:
            continue
        candidates.append(text)
        try:
            if isinstance(json.loads(text), dict):
                return text
        except (ValueError, TypeError):
            pass
    if candidates:
        return candidates[0]
    raise ValueError("Coffre illisible ou clé maître incorrecte")


def _read():
    """Lecture mise en cache : une seule dérivation PBKDF2 par version du fichier."""
    if not DATA_FILE.exists():
        _CACHE["signature"], _CACHE["data"] = None, {}
        return {}
    stat = DATA_FILE.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    if _CACHE["signature"] == signature and isinstance(_CACHE["data"], dict):
        return _CACHE["data"]
    data = json.loads(decrypt(DATA_FILE.read_text(encoding="utf-8")))
    if not isinstance(data, dict):
        raise ValueError("Structure du coffre invalide")
    _CACHE["signature"], _CACHE["data"] = signature, data
    return data


def _write(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(encrypt(json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    os.replace(tmp, DATA_FILE)  # écriture atomique
    try:
        os.chmod(DATA_FILE, 0o600)
    except OSError:
        pass
    _CACHE["signature"] = None
    _CACHE["data"] = data


def get(section, key, default=None):
    with _LOCK:
        return _read().get(section, {}).get(key, default)


def set(section, key, value):
    with _LOCK:
        data = dict(_read())
        data[section] = dict(data.get(section, {}))
        data[section][key] = value
        _write(data)


def delete(section, key):
    with _LOCK:
        data = dict(_read())
        data[section] = dict(data.get(section, {}))
        data[section].pop(key, None)
        _write(data)


def section(name, redact=True):
    with _LOCK:
        values = _read().get(name, {})
        if not redact:
            return dict(values)
        return {k: bool(v) for k, v in values.items()}


def secret(name, env_name=None):
    """Lit une valeur du coffre, puis de l'environnement en repli."""
    try:
        value = get("secrets", name)
    except (ValueError, OSError):
        value = None
    if value:
        return value
    return os.environ.get(env_name or name.upper(), "").strip()


def has(name, env_name=None):
    return bool(secret(name, env_name))
