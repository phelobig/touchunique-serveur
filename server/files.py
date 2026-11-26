# -*- coding: utf-8 -*-
"""Dossiers d'entreprises et de projets : dépôt de fichiers consultable par les IA."""

import base64
import hashlib
import json
import re
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ROOT = DATA / "dossiers"
INDEX = DATA / "dossiers-index.json"
LOCK = threading.RLock()
TEXT_EXT = {".txt", ".md", ".json", ".csv", ".xml", ".html", ".htm", ".py", ".js", ".log"}


def safe(value, fallback="dossier"):
    text = re.sub(r"[^\w\-À-ÿ. ]+", "_", str(value or ""), flags=re.UNICODE).strip(" .")
    return (text or fallback)[:80]


def _load():
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"files": []}


def _save(index):
    DATA.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def folder(company="", project="", name="Documents"):
    return ROOT / safe(company, "entreprise") / safe(project, "projet") / safe(name, "Documents")


def upload(company, project, folder_name, filename, content_b64, mime="", source="manuel"):
    if not filename:
        raise ValueError("Nom de fichier vide")
    raw = base64.b64decode(content_b64 or "")
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError("Fichier trop volumineux (12 Mo maximum)")
    target_dir = folder(company, project, folder_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = safe(filename, "fichier")
    path = target_dir / name
    path.write_bytes(raw)
    meta = {
        "id": hashlib.sha256((company + "/" + project + "/" + folder_name + "/" + name).encode("utf-8")).hexdigest()[:20],
        "company": company, "project": project, "folder": folder_name,
        "name": name, "size": len(raw), "mime": mime or "application/octet-stream",
        "source": source, "uploadedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "path": str(path.relative_to(BASE)).replace("\\", "/"),
    }
    with LOCK:
        index = _load()
        index["files"] = [f for f in index["files"] if f["id"] != meta["id"]]
        index["files"].insert(0, meta)
        _save(index)
    return meta


def listing(company=None, project=None, folder_name=None):
    items = _load()["files"]
    if company:
        items = [f for f in items if f.get("company") == company]
    if project:
        items = [f for f in items if f.get("project") == project]
    if folder_name:
        items = [f for f in items if f.get("folder") == folder_name]
    return items


def get(meta_id):
    for f in _load()["files"]:
        if f.get("id") == meta_id:
            return f
    return None


def download(meta_id):
    meta = get(meta_id)
    if not meta:
        raise ValueError("Fichier introuvable")
    path = BASE / meta["path"]
    return meta, base64.b64encode(path.read_bytes()).decode("ascii")


def remove(meta_id):
    with LOCK:
        index = _load()
        meta = next((f for f in index["files"] if f.get("id") == meta_id), None)
        if meta:
            path = BASE / meta["path"]
            if path.exists():
                path.unlink()
        index["files"] = [f for f in index["files"] if f.get("id") != meta_id]
        _save(index)
    return bool(meta)


def snippets(company, project, limit=18000):
    """Extrait le texte des fichiers utiles pour donner du contexte aux IA."""
    parts = []
    for meta in listing(company, project):
        path = BASE / meta["path"]
        if not path.exists() or path.suffix.lower() not in TEXT_EXT or path.stat().st_size > 400000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:6000]
        except Exception:
            continue
        parts.append("### " + meta["folder"] + "/" + meta["name"] + "\n" + text)
        if sum(len(p) for p in parts) >= limit:
            break
    return "\n\n".join(parts)[:limit]


def save_text(company, project, folder_name, filename, text, source="ia"):
    return upload(company, project, folder_name, filename,
                  base64.b64encode(text.encode("utf-8")).decode("ascii"),
                  "text/markdown; charset=utf-8", source)
