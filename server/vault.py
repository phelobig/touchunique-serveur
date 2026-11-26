# -*- coding: utf-8 -*-
"""Coffre chiffré côté serveur pour les clés API, tokens et jetons Google.

Chiffrement authentifié (encrypt-then-MAC) avec dérivation PBKDF2-SHA256.
Aucune clé n'est jamais renvoyée au navigateur : seuls des indicateurs
« connecté / non connecté » sont exposés.
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
KEY_FILE = BASE / ".vault_key"
DATA_FILE = BASE / "vault.json"
_LOCK = threading.RLock()


def _master():
    env = os.environ.get("TUS_VAULT_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip().encode("utf-8")
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
        stream += hmac.new(mac_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(salt + nonce + tag + cipher).decode("ascii")


def decrypt(blob):
    raw = base64.urlsafe_b64decode(str(blob).encode("ascii"))
    salt, nonce, tag, cipher = raw[:16], raw[16:32], raw[32:64], raw[64:]
    enc_key, mac_key = _keys(_master(), salt)
    expected = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Coffre illisible ou clé maître incorrecte")
    stream = b""
    counter = 0
    while len(stream) < len(cipher):
        stream += hmac.new(mac_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")


def _read():
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(decrypt(DATA_FILE.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _write(data):
    DATA_FILE.write_text(encrypt(json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    try:
        os.chmod(DATA_FILE, 0o600)
    except OSError:
        pass


def get(section, key, default=None):
    with _LOCK:
        return _read().get(section, {}).get(key, default)


def set(section, key, value):
    with _LOCK:
        data = _read()
        data.setdefault(section, {})[key] = value
        _write(data)


def delete(section, key):
    with _LOCK:
        data = _read()
        data.get(section, {}).pop(key, None)
        _write(data)


def section(name, redact=True):
    with _LOCK:
        values = _read().get(name, {})
        if not redact:
            return dict(values)
        return {k: bool(v) for k, v in values.items()}


def secret(name, env_name=None):
    """Lit une valeur du coffre, puis de l'environnement en repli."""
    value = get("secrets", name)
    if value:
        return value
    return os.environ.get(env_name or name.upper(), "").strip()


def has(name, env_name=None):
    return bool(secret(name, env_name))
