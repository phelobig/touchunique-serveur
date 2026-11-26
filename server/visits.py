# -*- coding: utf-8 -*-
"""Compteur de visiteurs du site public, persisté côté serveur.

Le suivi ne dépend ni de l'application ni d'une session ouverte : le site envoie
un signal au serveur à chaque visite. Le serveur ne conserve que des identifiants
opaque et des totaux — aucune adresse IP n'est stockée en clair.
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
STORE = DATA / "visits.json"
LOCK = threading.Lock()
RATE = {}
SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
WINDOW = 60
ONLINE_WINDOW = 300


def _day():
    return datetime.now().strftime("%Y-%m-%d")


def _load():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("unique_ids", [])
    state.setdefault("sessions", {})
    state.setdefault("days", {})
    state.setdefault("views", 0)
    return state


def _save(state):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE)


def _client_id(raw, ip):
    sid = str(raw or "").strip()
    if SID_RE.match(sid):
        return sid
    salt = os.environ.get("TUS_VAULT_KEY", "touchunique-visits")
    return hashlib.sha256((salt + "|" + str(ip or "")).encode("utf-8")).hexdigest()[:32]


def _summary_locked(state):
    now = time.time()
    sessions = state.get("sessions", {})
    for sid, entry in list(sessions.items()):
        if now - float(entry.get("last") or 0) > 86400 * 30:
            sessions.pop(sid, None)
    online = sum(1 for e in sessions.values() if now - float(e.get("last") or 0) <= ONLINE_WINDOW)
    return {
        "ok": True,
        "total": len(state.get("unique_ids", [])),
        "today": int(state.get("days", {}).get(_day(), 0)),
        "views": int(state.get("views", 0)),
        "online": online,
        "day": _day(),
    }


def summary():
    """Totaux publics : aucun détail nominatif n'est exposé."""
    with LOCK:
        state = _load()
        result = _summary_locked(state)
        _save(state)
    return result


def track(payload):
    """Enregistre un signal de visite. Un même visiteur n'est compté qu'une fois par jour."""
    now = time.time()
    ip = str(payload.get("_ip") or "")
    sid = _client_id(payload.get("sid"), ip)
    with LOCK:
        history = RATE.setdefault(sid, deque())
        while history and now - history[0] > WINDOW:
            history.popleft()
        if len(history) >= 3:
            state = _load()
            result = _summary_locked(state)
            _save(state)
            return result
        history.append(now)

        state = _load()
        sessions = state.setdefault("sessions", {})
        day = _day()
        entry = sessions.setdefault(sid, {"first": day, "last": now, "days": []})
        entry["last"] = now
        state["views"] = int(state.get("views", 0)) + 1
        if day not in entry.setdefault("days", []):
            entry["days"].append(day)
            days = state.setdefault("days", {})
            days[day] = int(days.get(day, 0)) + 1
        if sid not in state.setdefault("unique_ids", []):
            state["unique_ids"].append(sid)
        # Nettoage borné : 30 jours d'historique suffisent pour "en ligne".
        for key, value in list(sessions.items()):
            if now - float(value.get("last") or 0) > 86400 * 30:
                sessions.pop(key, None)
        _save(state)
        return _summary_locked(state)
