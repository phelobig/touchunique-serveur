# -*- coding: utf-8 -*-
"""Pipeline collaboratif : quatre agents IA qui se transmettent le même dossier.

Ordre : prospection → conception/devis → contact client → rapports/publication.
Chaque étape lit le dossier de l'entreprise (fichiers classés) et la sortie
des étapes précédentes. Les résultats sont enregistrés dans le dossier.
Aucune publication n'est annoncée sans identifiant renvoyé par l'API.
"""

import json
from datetime import date
from pathlib import Path

import files
import proxy
import vault

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "agents.json"

DEFAULT_AGENTS = [
    {
        "id": "prospection", "order": 1, "enabled": True,
        "name": "Agent 1 · Prospection & recherche",
        "provider": "perplexity",
        "role": "Cherche des prospects et vérifie les informations sur le web et les réseaux.",
        "prompt": "Tu es l'agent de prospection de Touch Unique Studio au Burkina-Faso. À partir du sujet, des recherches transmises et du dossier de l'entreprise, identifie 5 pistes qualifiées. Pour chacune : structure, besoin probable, service Touch Unique suggéré, source de l'information et phrase d'approche. Indique explicitement ce qui n'est pas vérifiable. Ne prétends jamais avoir contacté quelqu'un.",
    },
    {
        "id": "conception", "order": 2, "enabled": True,
        "name": "Agent 2 · Maquettes & devis",
        "provider": "gemini",
        "role": "Transforme les pistes en brief de conception, maquette décrite et devis.",
        "prompt": "Tu es l'agent conception de Touch Unique Studio. À partir du travail de la prospection et des fichiers du dossier, rédige : 1) un brief de conception précis (format, palette rouge sur fond clair, hiérarchie, livrables), 2) une description de maquette exploitable, 3) un devis détaillé en FCFA avec trois options et des délais. Reste réaliste et évite les promesses excessives.",
    },
    {
        "id": "contact", "order": 3, "enabled": True,
        "name": "Agent 3 · Contact client & production",
        "provider": "anthropic",
        "role": "Prépare le message de contact, le planning de production et les tâches.",
        "prompt": "Tu es l'agent production de Touch Unique Studio. À partir du brief et du devis reçus, prépare : 1) un message personnalisé de contact au client, 2) un planning de production avec jalons, 3) la liste des tâches assignées au studio, 4) les points à valider avant de contacter le client. Ne contacte pas le client toi-même et ne dis pas que c'est fait.",
    },
    {
        "id": "rapports", "order": 4, "enabled": True,
        "name": "Agent 4 · Rapports, contrôle & publication",
        "provider": "openai",
        "role": "Contrôle la cohérence, rédige les rapports d'inspection et les publications.",
        "prompt": "Tu es l'agent contrôle et publication de Touch Unique Studio. Vérifie la cohérence des trois étapes précédentes, signale les incohérences, rédige un rapport d'inspection court et 3 publications prêtes à diffuser. Pour chaque publication que tu veux envoyer, utilise exactement un bloc : [[PUBLICATION:facebook|instagram|linkedin]] puis le texte puis [[/PUBLICATION]]. Sans bloc, aucune publication ne sera envoyée.",
    },
]


def config():
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text(encoding="utf-8"))
            if isinstance(saved, list) and saved:
                return saved
        except Exception:
            pass
    return [dict(a) for a in DEFAULT_AGENTS]


def save_config(agents):
    CONFIG.write_text(json.dumps(agents, ensure_ascii=False, indent=2), encoding="utf-8")
    return agents


def overview():
    providers = proxy.configured_providers()
    return {
        "ok": True,
        "agents": config(),
        "providers": providers,
        "anyProvider": any(providers.values()),
        "queue": len(config()),
    }


def _provider_for(agent, providers):
    wanted = str(agent.get("provider") or "auto").lower()
    if providers.get(wanted):
        return wanted
    for name in ("perplexity", "gemini", "anthropic", "openai"):
        if providers.get(name):
            return name
    return ""


def _context(company, project, topic, research, previous):
    parts = ["Entreprise : " + str(company or "non précisée"),
             "Projet : " + str(project or "non précisé"),
             "Sujet : " + str(topic or "prospection et création"),
             "Recherches transmises par l'utilisateur :\n" + str(research or "aucune")]
    dossier = files.snippets(company, project)
    if dossier:
        parts.append("Fichiers du dossier (sources autorisées) :\n" + dossier)
    if previous:
        parts.append("Travail des agents précédents (à utiliser, pas à recopier) :\n" + previous[-14000:])
    return "\n\n".join(parts)


def run_case(payload):
    company = str(payload.get("company") or "").strip()[:120]
    project = str(payload.get("project") or "").strip()[:120]
    topic = str(payload.get("topic") or "").strip()[:1500]
    research = str(payload.get("research") or "").strip()[:30000]
    publish = bool(payload.get("publish"))
    providers = proxy.configured_providers()
    if not any(providers.values()):
        raise RuntimeError("Aucun fournisseur IA connecté : saisissez les clés dans les réglages de l'application.")

    agents = sorted([a for a in config() if a.get("enabled", True)], key=lambda a: int(a.get("order", 99)))
    if not agents:
        raise RuntimeError("Aucun agent activé dans la configuration du pipeline.")
    today = date.today().isoformat()
    trace = []
    previous = []
    published = []

    for agent in agents:
        provider = _provider_for(agent, providers)
        if not provider:
            raise RuntimeError("Fournisseur IA indisponible pour " + agent.get("name", agent["id"]))
        prompt = (agent.get("prompt") or "") + "\n\n---\n\n" + _context(company, project, topic, research, "\n\n".join(previous))
        try:
            result = proxy.run_ai({
                "provider": provider,
                "prompt": prompt,
                "system": "Tu travailles en collaboration avec les autres agents de Touch Unique Studio. Réponds en français, de façon factuelle et actionnable.",
                "maxTokens": 1800,
            })
        except Exception as e:
            trace.append({"id": agent["id"], "name": agent.get("name"), "ok": False,
                          "provider": provider, "error": str(e)[:500]})
            return {"ok": False, "error": "Étape " + agent["id"] + " impossible : " + str(e)[:400],
                    "company": company, "project": project, "stages": trace, "published": published}
        text = result.get("text", "")
        meta = files.save_text(company, project, "IA-" + agent["id"], today + ".md", text, provider)
        step = {"id": agent["id"], "name": agent.get("name"), "ok": True,
                "provider": result.get("provider"), "model": result.get("model"),
                "text": text, "file": meta["path"]}
        trace.append(step)
        previous.append("### " + str(agent.get("name") or agent["id"]) + "\n" + text)

        if agent["id"] == "rapports" and publish:
            chunks = []
            for part in text.split("[[PUBLICATION:"):
                if "]]" not in part:
                    continue
                network, _, rest = part.partition("]]")
                body, _, _ = rest.partition("[[/PUBLICATION]]")
                network = network.strip().lower()
                body = body.strip()
                if network in ("facebook", "instagram", "linkedin") and body:
                    chunks.append((network, body))
            for network, body in chunks:
                if not proxy.configured_networks().get(network):
                    published.append({"network": network, "ok": False, "error": "Compte non connecté"})
                    continue
                try:
                    out = proxy.run_publish({"network": network, "text": body})
                    published.append({"network": network, "ok": bool(out.get("id")), "id": out.get("id")})
                except Exception as e:
                    published.append({"network": network, "ok": False, "error": str(e)[:300]})

    return {"ok": True, "company": company, "project": project,
            "stages": trace, "published": published,
            "note": "Aucune publication envoyée." if not published else ""}
