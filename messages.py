# -*- coding: utf-8 -*-
"""Messagerie site ↔ application, résultats des robots et notifications push.

Les messages sont stockés sur le serveur (pas seulement dans le navigateur) pour
que l'application puisse les recevoir même lorsque la fenêtre du site est fermée.
Les pièces jointes sont des fichiers locaux au serveur, avec des noms aléatoires.
Aucun statut « envoyé » n'est renvoyé sans écriture réussie sur le disque.
"""

import base64
import binascii
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
STORE = DATA / "messages.json"
FILES = DATA / "messages"
LOCK = threading.Lock()
RATE = {}

THREAD_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MIME_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a",
    "audio/wav": "wav", "application/pdf": "pdf", "text/plain": "txt",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_BYTES = 8 * 1024 * 1024
MAX_PER_WINDOW = 40
WINDOW_SECONDS = 600


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _load():
    FILES.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("threads", {})
    state.setdefault("subscriptions", [])
    state.setdefault("lastPush", "")
    return state


def _save(state):
    DATA.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE)


def _allowed(thread):
    now = time.time()
    q = RATE.setdefault(thread, deque())
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    if len(q) >= MAX_PER_WINDOW:
        return False
    q.append(now)
    return True


def _clean(value, limit=3000):
    return str(value or "").strip()[:limit]


def _vapid():
    import vault
    pub = vault.secret("vapid_public", "VAPID_PUBLIC_KEY")
    private = vault.secret("vapid_private", "VAPID_PRIVATE_KEY")
    subject = vault.secret("vapid_subject", "VAPID_SUBJECT") or "mailto:jasonsary5@gmail.com"
    return pub, private, subject


def ensure_keys():
    """Génère des clés VAPID une seule fois et les garde dans le coffre chiffré."""
    pub, private, subject = _vapid()
    if pub and private:
        return True
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        import base64 as b64
    except ImportError:
        return False
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    encode = lambda b: b64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")
    public = encode(raw)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    import vault
    vault.set("secrets", "vapid_public", public)
    vault.set("secrets", "vapid_private", private_pem)
    vault.set("secrets", "vapid_subject", subject)
    return True


def config():
    pub, private, _ = _vapid()
    return {
        "ok": True,
        "enabled": bool(pub and private),
        "publicKey": pub or "",
        "maxBytes": MAX_BYTES,
        "kinds": ["text", "file", "voice", "photo"],
    }


def _save_attachment(payload, mime, kind):
    mime = str(mime or "").split(";")[0].strip().lower()
    ext = MIME_EXT.get(mime)
    if kind == "voice" and mime not in ("audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav"):
        raise ValueError("Format audio non pris en charge.")
    if not ext:
        raise ValueError("Type de fichier non autorisé : " + (mime or "inconnu"))
    try:
        raw = base64.b64decode(str(payload or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Pièce jointe invalide (base64 attendu).")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Fichier vide ou trop volumineux (8 Mo maximum).")
    name = secrets.token_hex(18) + "." + ext
    (FILES / name).write_bytes(raw)
    return {"url": "/api/messages/file/" + name, "name": name, "mime": mime, "bytes": len(raw)}


def post(data):
    data = data or {}
    thread = _clean(data.get("thread"), 64)
    if not THREAD_RE.match(thread):
        raise ValueError("Identifiant de conversation invalide.")
    if not _allowed(thread):
        raise ValueError("Trop de messages envoyés récemment. Réessayez dans quelques minutes.")
    admin = bool(data.get("admin"))
    if not admin and _clean(data.get("token"), 64) != thread:
        raise ValueError("Jeton de conversation invalide.")
    kind = _clean(data.get("kind") or "text", 20)
    if kind not in ("text", "file", "voice", "photo"):
        raise ValueError("Type de message inconnu.")
    text = _clean(data.get("text"), 4000)
    attachment = None
    if data.get("attachment"):
        attachment = _save_attachment(data.get("content"), data.get("mime"), kind)
    if not text and not attachment:
        raise ValueError("Message vide.")
    message = {
        "id": secrets.token_hex(12),
        "thread": thread,
        "direction": "out" if admin else "in",
        "kind": kind,
        "text": text,
        # Une réponse administrateur porte toujours l'identité du studio :
        # sans cela le site l'afficherait sous le nom du client.
        "name": "Touch Unique Studio" if admin else _clean(data.get("name"), 100),
        "email": "" if admin else _clean(data.get("email"), 160).lower(),
        "phone": "" if admin else _clean(data.get("phone"), 40),
        "need": "" if admin else _clean(data.get("need"), 3000),
        "attachment": attachment,
        "at": _now(),
    }
    with LOCK:
        state = _load()
        t = state["threads"].setdefault(thread, {"id": thread, "updatedAt": "", "messages": []})
        if not admin:
            t["client"] = {
                "name": message["name"] or t.get("client", {}).get("name", ""),
                "email": message["email"] or t.get("client", {}).get("email", ""),
                "phone": message["phone"] or t.get("client", {}).get("phone", ""),
            }
        t["messages"].append(message)
        t["messages"] = t["messages"][-500:]
        t["updatedAt"] = message["at"]
        _save(state)
    try:
        push(message)
    except Exception:
        # Une notification échouée ne doit jamais effacer le message enregistré.
        pass
    return {"ok": True, "message": message}


def listing(thread=None, since=None, admin=False):
    with LOCK:
        state = _load()
    threads = state["threads"]
    if not admin:
        if not thread or not THREAD_RE.match(thread):
            raise ValueError("Conversation introuvable.")
        threads = {thread: threads.get(thread, {"id": thread, "messages": []})}
    else:
        # Les conversations les plus récentes d'abord.
        threads = dict(sorted(threads.items(), key=lambda kv: kv[1].get("updatedAt", ""), reverse=True)[:80])
    result = []
    for tid, t in threads.items():
        messages = [m for m in t.get("messages", []) if not since or str(m.get("at", "")) > str(since)]
        result.append({
            "id": tid,
            "client": t.get("client", {}),
            "updatedAt": t.get("updatedAt", ""),
            "messages": messages[-200:],
        })
    return {"ok": True, "threads": result, "since": since or "", "count": sum(len(t["messages"]) for t in result)}


def attachment(name):
    clean = os.path.basename(str(name or ""))
    if not re.match(r"^[A-Za-z0-9]{36}\.[a-z0-9]{2,5}$", clean):
        raise ValueError("Pièce jointe introuvable.")
    path = FILES / clean
    if not path.is_file():
        raise ValueError("Pièce jointe introuvable.")
    mime = MIME_EXT.get(clean.rsplit(".", 1)[-1], "application/octet-stream")
    reverse = {v: k for k, v in MIME_EXT.items()}
    return reverse.get(clean.rsplit(".", 1)[-1], mime), path.read_bytes()


def subscribe(data):
    data = data or {}
    endpoint = _clean(data.get("endpoint"), 1000)
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    if not endpoint.startswith("https://"):
        raise ValueError("Abonnement de notification invalide.")
    if not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Clés de notification manquantes.")
    thread = _clean(data.get("thread"), 64)
    role = "admin" if data.get("role") == "admin" else "client"
    with LOCK:
        state = _load()
        subs = [s for s in state["subscriptions"] if s.get("endpoint") != endpoint]
        subs.append({"endpoint": endpoint, "keys": keys, "thread": thread, "role": role, "at": _now()})
        state["subscriptions"] = subs[-500:]
        _save(state)
    return {"ok": True, "enabled": config()["enabled"], "subscriptions": len(subs)}


def push(message):
    pub, private, subject = _vapid()
    if not pub or not private:
        return {"sent": 0, "reason": "clés VAPID non configurées"}
    try:
        from pywebpush import webpush
    except ImportError:
        return {"sent": 0, "reason": "pywebpush non installé"}
    with LOCK:
        state = _load()
    targets = [s for s in state["subscriptions"]
               if s.get("role") == "admin" or s.get("thread") == message.get("thread")]
    payload = json.dumps({
        "title": "Touch Unique — " + ("Nouveau message" if message.get("direction") == "in" else "Réponse"),
        "body": (message.get("name") or "Client") + " : " + (message.get("text") or "Pièce jointe reçue")[:140],
        "thread": message.get("thread"),
        "url": "https://phelobig.github.io/touchunique-site/#contact",
    })
    sent = 0
    for sub in targets:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                data=payload,
                vapid_private_key=private,
                vapid_claims={"sub": subject},
            )
            sent += 1
        except Exception:
            continue
    if sent:
        with LOCK:
            state = _load()
            state["lastPush"] = _now()
            _save(state)
    return {"sent": sent, "targets": len(targets)}


def overview():
    with LOCK:
        state = _load()
    return {
        "ok": True,
        "enabled": config()["enabled"],
        "threads": len(state["threads"]),
        "messages": sum(len(t.get("messages", [])) for t in state["threads"].values()),
        "subscriptions": len(state["subscriptions"]),
        "lastPush": state.get("lastPush", ""),
    }
