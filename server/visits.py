# -*- coding: utf-8 -*-
"""Compteur de visiteurs du site public, persisté côté serveur.

Le suivi ne dépend ni de l'application ni d'une session ouverte : le site envoie
un signal au serveur à chaque visite. Les totaux publics ne contiennent aucun
détail. Les détails administratifs (IP, appareil, contacts transmis) sont dans un
store séparé, borné et accessible uniquement avec la clé X-Tus-Key.
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
DETAILS = DATA / "visits-details.json"
LOCK = threading.Lock()
RATE = {}
SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
WINDOW = 60
ONLINE_WINDOW = 300
DETAIL_LIMIT = 250
BRANDS = (
    "Samsung", "Xiaomi", "Redmi", "Poco", "Oppo", "Realme", "OnePlus", "Tecno",
    "Infinix", "Itel", "Huawei", "Honor", "Google", "Motorola", "Nokia", "Sony",
    "Apple", "Microsoft", "Dell", "HP", "Lenovo", "Asus", "Acer"
)


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


def _load_details():
    try:
        state = json.loads(DETAILS.read_text(encoding="utf-8"))
        return state if isinstance(state, list) else []
    except (OSError, ValueError):
        return []


def _save_details(items):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DETAILS.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DETAILS)


def _clean(value, size):
    return str(value or "").strip()[:size]


def device_info(ua):
    """Marque et modèle déduits de l'agent utilisateur, sans identification matérielle."""
    ua = str(ua or "")
    brand = next((b for b in BRANDS if b.lower() in ua.lower()), "")
    model = ""
    m = re.search(r"(?:Android[^;)]*;\s*)([^;)]{2,40})", ua)
    if m:
        model = m.group(1).strip()
    elif "iPhone" in ua:
        model = "iPhone"
    elif "iPad" in ua:
        model = "iPad"
    return {
        "brand": brand,
        "model": model[:40],
        "platform": ("Android" if "Android" in ua else
                     "iOS" if ("iPhone" in ua or "iPad" in ua) else
                     "Windows" if "Windows" in ua else
                     "macOS" if "Macintosh" in ua else
                     "Linux" if "Linux" in ua else "Inconnu")
    }


def _detail(payload, sid, now):
    item = {
        "at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "sid": sid,
        "ip": _clean(payload.get("_ip"), 64),
        "userAgent": _clean(payload.get("ua"), 300),
        "lang": _clean(payload.get("lang"), 20),
        "timezone": _clean(payload.get("tz"), 60),
        "screen": _clean(payload.get("screen"), 40),
        "page": _clean(payload.get("page"), 120),
        "referrer": _clean(payload.get("ref"), 300),
        "device": device_info(payload.get("ua"))
    }
    # Les contacts ne sont enregistrés que s'ils ont été réellement transmis
    # par le visiteur (formulaire ou messagerie), jamais avant son consentement.
    contact = payload.get("contact")
    if isinstance(contact, dict):
        item["contact"] = {
            "name": _clean(contact.get("name"), 80),
            "email": _clean(contact.get("email"), 120),
            "phone": _clean(contact.get("phone"), 40)
        }
        item["contact"] = {k: v for k, v in item["contact"].items() if v}
        if not item["contact"]:
            item.pop("contact", None)
    return item


def details(limit=100):
    """Vue administrative : détails bornés, jamais exposés sur /api/visits."""
    try:
        count = max(1, min(int(limit), DETAIL_LIMIT))
    except (TypeError, ValueError):
        count = 100
    with LOCK:
        items = _load_details()
        return {
            "ok": True,
            "count": len(items),
            "summary": _summary_locked(_load()),
            "items": list(reversed(items[-count:]))
        }


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

        recorded = _load_details()
        recorded.append(_detail(payload, sid, now))
        if len(recorded) > DETAIL_LIMIT:
            recorded = recorded[-DETAIL_LIMIT:]
        _save_details(recorded)

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
