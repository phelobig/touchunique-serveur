# -*- coding: utf-8 -*-
"""Catalogue synchronisé : prix, offres et galeries d'images modifiés dans
l'application, consultables par le site public.

L'état est un surcouche du catalogue canonique (site/catalogue.json) :
  overrides : modifications des offres existantes, par identifiant
  added     : nouvelles offres créées dans l'application
  removed   : identifiants des offres canoniques masquées
Aucune clé API ni donnée privée n'est stockée ici.
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FILE = DATA / "catalog.json"

MAX_IMAGES = 12
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # image réduite côté navigateur


def empty():
    return {"overrides": {}, "added": [], "removed": [], "updatedAt": ""}


def _clean_product(product):
    if not isinstance(product, dict):
        return None
    pid = str(product.get("id") or "").strip()[:120]
    if not pid:
        return None
    clean = dict(product)
    clean["id"] = pid
    clean["name"] = str(product.get("name") or pid)[:160]
    clean["price"] = max(0, int(product.get("price") or 0))
    clean["unit"] = str(product.get("unit") or "forfait")[:60]
    clean["short"] = str(product.get("short") or "")[:600]
    clean["desc"] = str(product.get("desc") or "")[:4000]
    clean["category"] = str(product.get("category") or "outils")[:60]
    clean["delay"] = str(product.get("delay") or "")[:60]
    clean["badge"] = str(product.get("badge") or "")[:80]
    imgs = product.get("images")
    if not isinstance(imgs, list):
        imgs = [product.get("img")] if product.get("img") else []
    kept = []
    for value in imgs[:MAX_IMAGES]:
        text = str(value or "").strip()
        if not text:
            continue
        if text.startswith("data:image/"):
            # Les images sont réduites côté navigateur ; on borne la taille.
            if len(text) > MAX_IMAGE_BYTES * 2:
                continue
        elif not (text.startswith("https://") or text.startswith("/") or text.startswith("assets/")):
            # Noms de fichiers relatifs du catalogue canonique (ex. identite-01.webp).
            if ("://" in text or ".." in text or "\\" in text or len(text) > 300):
                continue
        kept.append(text[:MAX_IMAGE_BYTES * 2])
    clean["images"] = kept
    clean["img"] = kept[0] if kept else ""
    for key in ("deliverables", "ai"):
        value = product.get(key)
        clean[key] = [str(v)[:300] for v in value[:20]] if isinstance(value, list) else []
    clean["popular"] = bool(product.get("popular"))
    return clean


def read():
    if FILE.exists():
        try:
            state = json.loads(FILE.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                out = empty()
                out["overrides"] = state.get("overrides") if isinstance(state.get("overrides"), dict) else {}
                out["added"] = state.get("added") if isinstance(state.get("added"), list) else []
                out["removed"] = state.get("removed") if isinstance(state.get("removed"), list) else []
                out["updatedAt"] = str(state.get("updatedAt") or "")
                return out
        except Exception:
            pass
    return empty()


def write(payload):
    payload = payload if isinstance(payload, dict) else {}
    state = empty()
    overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
    for pid, value in overrides.items():
        clean = _clean_product(dict(value or {}, id=pid))
        if clean:
            state["overrides"][str(pid)[:120]] = clean
    added = payload.get("added") if isinstance(payload.get("added"), list) else []
    for value in added[:200]:
        clean = _clean_product(value)
        if clean:
            state["added"].append(clean)
    removed = payload.get("removed") if isinstance(payload.get("removed"), list) else []
    state["removed"] = [str(v)[:120] for v in removed[:200] if v]
    state["updatedAt"] = str(payload.get("updatedAt") or "")
    DATA.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def status():
    state = read()
    return {
        "ok": True, "catalog": state,
        "counts": {
            "overrides": len(state["overrides"]),
            "added": len(state["added"]),
            "removed": len(state["removed"]),
        },
        "updatedAt": state["updatedAt"],
    }
