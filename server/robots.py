# -*- coding: utf-8 -*-\n"""Robots Touch Unique — tâches quotidiennes réelles, exécutées côté serveur.\n\nUn robot génère du contenu avec l’IA connectée (ChatGPT / Gemini / Claude),\nconserve le résultat dans server/output/ et, pour le robot de publication,\nenvoie réellement le contenu aux réseaux sociaux dont les tokens sont définis.\nAucun résultat n’est marqué « publié » si l’API ne l’a pas confirmé.\n"""

from datetime import date
from pathlib import Path

import proxy

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
STATE_FILE = BASE / "robot_state.json"
CONFIG_FILE = BASE / "robot_config.json"

ROBOTS = [
    {
        "id": "veille",
        "name": "Veille techno & services",
        "kind": "veille",
        "icon": "⌕",
        "desc": "Chaque jour : 5 informations utiles dans la technologie, le design, la vidéo et les outils du studio.",
        "topic": "actualités technologie, design, vidéo, réseaux sociaux et outils créatifs utiles à Touch Unique Studio",
    },
    {
        "id": "publication",
        "name": "Publication automatique",
        "kind": "publication",
        "icon": "▶",
        "desc": "Chaque jour : 3 publications générées puis envoyées aux comptes Facebook, Instagram et LinkedIn connectés.",
        "topic": "l’identité visuelle, la vidéo courte et l’automatisation IA pour les petites entreprises au Burkina-Faso",
    },
    {
        "id": "conception",
        "name": "Nouvelle conception",
        "kind": "design",
        "icon": "◆",
        "desc": "Chaque jour : un brief de conception complet, prêt à être confié au studio ou à un concepteur.",
        "topic": "un visuel de marque rouge sur fond clair pour une offre Touch Unique Studio",
    },
    {
        "id": "prospection",
        "name": "Recherche de prospects",
        "kind": "prospect",
        "icon": "◎",
        "desc": "Chaque jour : 5 pistes qualifiées avec une approche personnalisée et le service suggéré.",
        "topic": "commerces, créateurs et petites structures d’Ouagadougou ayant besoin d’identité, de vidéo ou de contenu",
    },
]

PROMPTS = {
    "veille": "Fais une veille actuelle et concise sur {topic}. Donne 5 points concrets, chacun avec une idée d’application pour Touch Unique Studio. Reste factuel et indique quand une information ne peut pas être vérifiée.",
    "publication": "Rédige 3 publications prêtes à publier sur {topic}. Pour chacune : un titre court, un texte de 3 à 5 lignes et 3 hashtags. Ton professionnel, direct, sans promesse excessive.",
    "design": "Rédige un brief de conception précis pour {topic} : direction artistique, format, hiérarchie visuelle, palette, éléments à éviter et livrables attendus.",
    "prospect": "Propose 5 prospects potentiels autour de {topic}. Pour chacun : type de structure, besoin probable, service Touch Unique suggéré et une phrase d’approche personnalisée. Ne prétends pas disposer de coordonnées réelles.",
}


def read_state():
    try:
        return json_loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def json_loads(text):
    import json
    return json.loads(text or "{}")


def write_state(state):
    import json
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def folder_slug(value):
    import re
    import unicodedata
    clean = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9-]+", "-", clean).strip("-")[:60]
    return "IA-" + (clean or "robot")


def config():
    """Configuration quotidienne : nom, icône, dossier propre, heure, fournisseur, consigne."""
    import json
    base = [dict(r, enabled=True, hour=8, provider="auto",
                 folder=folder_slug(r["name"])) for r in ROBOTS]
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            by_id = {x["id"]: x for x in saved if isinstance(x, dict) and x.get("id")}
            for item in base:
                item.update({k: v for k, v in by_id.get(item["id"], {}).items()
                             if k in ("enabled", "hour", "provider", "topic", "desc",
                                      "name", "icon", "color", "folder")})
                item["folder"] = folder_slug(item.get("folder") or item.get("name") or item["id"])
        except Exception:
            pass
    return base


def save_config(items):
    import json
    allowed = {r["id"] for r in ROBOTS}
    clean = []
    for item in items or []:
        if not isinstance(item, dict) or item.get("id") not in allowed:
            continue
        clean.append({
            "id": item["id"],
            "enabled": bool(item.get("enabled", True)),
            "hour": max(0, min(23, int(item.get("hour", 8)))),
            "provider": str(item.get("provider") or "auto")[:30],
            "topic": str(item.get("topic") or "")[:600],
            "desc": str(item.get("desc") or "")[:300],
            "name": str(item.get("name") or "")[:120],
            "icon": str(item.get("icon") or "")[:12],
            "color": str(item.get("color") or "")[:20],
            "folder": folder_slug(item.get("folder") or item.get("name") or item["id"]),
        })
    if not clean:
        clean = config()
    CONFIG_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config()


def overview():
    state = read_state()
    return {
        "ok": True,
        "autorun": proxy.env_flag("TUS_ROBOT_AUTORUN"),
        "hour": int(proxy.os.environ.get("TUS_ROBOT_HOUR", "8")),
        "ai": proxy.configured_providers(),
        "social": proxy.configured_networks(),
        "robots": [
            dict(r, lastRun=state.get(r["id"], {}).get("at"), lastResult=state.get(r["id"], {}).get("result"))
            for r in config()
        ],
    }


def run_robot(rid, dry_run=False, publish=True):
    robot = next((r for r in config() if r["id"] == rid), None)
    if not robot:
        return {"ok": False, "error": "Robot introuvable : " + str(rid)}
    if not any(proxy.configured_providers().values()):
        return {"ok": False, "error": "Aucun fournisseur IA connecté sur le serveur."}

    prompt = PROMPTS[robot["kind"]].format(topic=robot.get("topic") or robot["topic"])
    system = ("Tu es l’assistant opérationnel de Touch Unique Studio au Burkina-Faso. "
              "Réponds en français. Ne simule jamais une publication, un paiement ou une donnée que tu n’as pas.")
    try:
        result = proxy.run_ai({"provider": robot.get("provider") or "auto", "prompt": prompt,
                               "system": system, "maxTokens": 1200})
    except Exception as e:
        return {"ok": False, "error": "Génération IA impossible : " + str(e)[:500]}

    text = result["text"]
    folder = OUTPUT / folder_slug(robot.get("folder") or robot.get("name") or rid)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (date.today().isoformat() + ".md")
    path.write_text("# " + robot["name"] + "\n\n" + text + "\n", encoding="utf-8")

    out = {
        "ok": True,
        "id": rid,
        "name": robot["name"],
        "icon": robot.get("icon", ""),
        "folder": robot.get("folder", ""),
        "provider": result["provider"],
        "model": result["model"],
        "text": text,
        "file": str(path.relative_to(BASE)).replace("\\", "/"),
        "published": [],
    }

    if rid == "publication" and publish and not dry_run:
        networks = proxy.configured_networks()
        for network, ready in networks.items():
            if not ready:
                continue
            try:
                pub = proxy.run_publish({"network": network, "text": text[:3000]})
                out["published"].append({"network": network, "ok": True, "id": pub.get("id")})
            except Exception as e:
                out["published"].append({"network": network, "ok": False, "error": str(e)[:300]})
    elif rid == "publication" and dry_run:
        out["note"] = "Aperçu généré : aucune publication envoyée (mode dryRun)."

    state = read_state()
    state[rid] = {
        "at": proxy.now_iso(),
        "date": date.today().isoformat(),
        "result": "publié" if out["published"] and all(p["ok"] for p in out["published"]) else ("généré" if out["ok"] else "erreur"),
    }
    write_state(state)
    return out


def run_all(dry_run=False):
    return [run_robot(r["id"], dry_run=dry_run) for r in config() if r.get("enabled", True)]


def due(hour=None):
    """Robots activés dont l'heure est passée et qui n'ont pas tourné aujourd'hui."""
    today = date.today().isoformat()
    state = read_state()
    due_list = []
    for r in config():
        if not r.get("enabled", True):
            continue
        if hour is not None and int(r.get("hour", 8)) > hour:
            continue
        entry = state.get(r["id"], {})
        if entry.get("date") != today:
            due_list.append(r["id"])
    return due_list
