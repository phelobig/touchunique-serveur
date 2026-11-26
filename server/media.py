# -*- coding: utf-8 -*-
"""Analyse de fichiers multimédia par IA, puis création d'une mission.

Types acceptés : images (JPEG, PNG, WebP, GIF, HEIC), audio (MP3, WAV, M4A,
OGG, WebM), vidéo (MP4, WebM, MOV, AVI) et documents (PDF, texte, CSV, HTML).
Le fichier est d'abord classé dans le dossier entreprise/projet, puis analysé.
Le résultat structuré est enregistré dans « IA-analyse » et peut alimenter
directement le pipeline collaboratif des quatre agents.

Aucune donnée n'est envoyée à un service qui n'a pas été connecté dans les
réglages : le fournisseur est choisi parmi les clés présentes dans le coffre.
"""

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import files
import proxy

BASE = Path(__file__).resolve().parent

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif", "image/bmp"}
AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/wav", "audio/x-wav",
               "audio/ogg", "audio/webm", "audio/aac", "audio/flac", "audio/x-m4a"}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo", "video/mpeg", "video/3gpp"}
DOC_TYPES = {"application/pdf", "text/plain", "text/markdown", "text/csv", "text/html", "application/json",
             "application/xml", "text/xml"}

MAX_BYTES = 20 * 1024 * 1024  # limite d'inline Gemini, cohérente avec l'upload (12 Mo)

SYSTEM_PROMPT = (
    "Tu es l'analyste multimédia de Touch Unique Studio au Burkina-Faso. "
    "Tu examines le fichier fourni avec précision et neutralité. "
    "Tu extrais uniquement ce qui est réellement visible ou audible, sans inventer. "
    "Tu signales explicitement ce qui est illisible, ambigu ou non vérifiable. "
    "Réponds en français, sous forme de JSON valide avec les clés : "
    "summary (2 phrases), details (liste de faits observés), "
    "entities (objet avec names, organisations, phones, emails, dates, amounts, urls — listes), "
    "suggestedMission (une phrase d'objectif actionnable pour le studio), "
    "confidence (élevée/moyenne/faible)."
)

FALLBACK_SYSTEM = (
    "Tu es l'analyste multimédia de Touch Unique Studio. Décris précisément le fichier, "
    "extrais les informations utiles (noms, contacts, dates, montants, besoins) et propose "
    "une mission de création ou de prospection. Ne prétends jamais avoir contacté quelqu'un. "
    "Réponds en français avec des titres clairs."
)


def kind_of(mime="", name=""):
    """Retourne image, audio, video, document ou autre."""
    m = (mime or "").lower().split(";")[0].strip()
    if m in IMAGE_TYPES or m.startswith("image/"):
        return "image"
    if m in AUDIO_TYPES or m.startswith("audio/"):
        return "audio"
    if m in VIDEO_TYPES or m.startswith("video/"):
        return "video"
    if m in DOC_TYPES or m.startswith("text/"):
        return "document"
    ext = Path(str(name or "")).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".bmp"}:
        return "image"
    if ext in {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac", ".opus"}:
        return "audio"
    if ext in {".mp4", ".webm", ".mov", ".avi", ".mkv", ".3gp"}:
        return "video"
    if ext in {".pdf", ".txt", ".md", ".csv", ".html", ".json", ".xml", ".docx"}:
        return "document"
    return "autre"


def _json_from_text(text):
    """Extrait un objet JSON d'une réponse IA même si elle contient du texte autour."""
    raw = str(text or "").strip()
    if not raw:
        return None
    # Supprime les balises de code Markdown éventuelles.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                continue
    return None


def _normalize(parsed, fallback_text):
    """Garantit une forme stable, quel que soit le fournisseur."""
    if not isinstance(parsed, dict):
        parsed = {}
    entities = parsed.get("entities") if isinstance(parsed.get("entities"), dict) else {}
    clean_entities = {}
    for key in ("names", "organisations", "phones", "emails", "dates", "amounts", "urls"):
        value = entities.get(key, [])
        if isinstance(value, list):
            clean_entities[key] = [str(v)[:200] for v in value[:12]]
        elif value:
            clean_entities[key] = [str(value)[:200]]
        else:
            clean_entities[key] = []
    details = parsed.get("details", [])
    if not isinstance(details, list):
        details = [str(details)] if details else []
    return {
        "summary": str(parsed.get("summary") or fallback_text[:600])[:1200],
        "details": [str(d)[:400] for d in details[:25]],
        "entities": clean_entities,
        "suggestedMission": str(parsed.get("suggestedMission") or parsed.get("mission") or "")[:800],
        "confidence": str(parsed.get("confidence") or "non précisée")[:40],
        "raw": fallback_text[:30000],
    }


def _question_prompt(question, kind):
    base = (
        "Analyse ce fichier " + kind + " pour une mission de Touch Unique Studio. "
        "Extrais toutes les informations exploitables et réponds en JSON selon la consigne."
    )
    if question:
        base += "\n\nQuestion précise de l'utilisateur : " + str(question)[:1200]
    return base


def _gemini_multimodal(data_b64, mime, kind, question, max_tokens=2200):
    key = proxy._secret("gemini_api_key", "GEMINI_API_KEY")
    model = os.environ.get("GEMINI_VISION_MODEL", "gemini-1.5-flash")
    parts = [
        {"text": SYSTEM_PROMPT + "\n\n" + _question_prompt(question, kind)},
        {"inline_data": {"mime_type": mime or "application/octet-stream", "data": data_b64}},
    ]
    url = ("https://generativelanguage.googleapis.com/v1beta/models/" + model +
           ":generateContent?key=" + urllib.parse.quote(key, safe=""))
    _, body = proxy.http_json(url, {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    })
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini n'a pas retourné d'analyse (contenu bloqué ou vide)")
    text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
    return text, model


def _openai_vision(data_b64, mime, question, max_tokens=2200):
    key = proxy._secret("openai_api_key", "OPENAI_API_KEY")
    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": _question_prompt(question, "image")},
                {"type": "image_url", "image_url": {"url": "data:" + (mime or "image/png") + ";base64," + data_b64}},
            ]},
        ],
    }
    _, body = proxy.http_json("https://api.openai.com/v1/chat/completions", payload,
                              {"Authorization": "Bearer " + key})
    return body["choices"][0]["message"]["content"], model


def _openai_transcribe(raw, name, mime):
    """Transcription audio réelle via Whisper (multipart, stdlib uniquement)."""
    key = proxy._secret("openai_api_key", "OPENAI_API_KEY")
    boundary = "----TouchUniqueBoundary" + os.urandom(12).hex()
    lines = []
    def field(key_name, value):
        lines.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key_name + "\"\r\n\r\n" + str(value) + "\r\n").encode("utf-8"))
    field("model", os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1"))
    field("response_format", "verbose_json")
    lines.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" +
                  re.sub(r"[\r\n\"]", "_", name or "audio") + "\"\r\nContent-Type: " +
                  (mime or "application/octet-stream") + "\r\n\r\n").encode("utf-8"))
    lines.append(raw)
    lines.append(("\r\n--" + boundary + "--\r\n").encode("utf-8"))
    body = b"".join(lines)
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            parsed = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("Transcription impossible : HTTP " + str(e.code) + " " + e.read().decode("utf-8", "replace")[:300])
    text = parsed.get("text") or ""
    segments = parsed.get("segments") or []
    details = [str(s.get("text", ""))[:400] for s in segments[:25] if s.get("text")]
    return text, details


def _anthropic_vision(data_b64, mime, question, max_tokens=2200):
    key = proxy._secret("anthropic_api_key", "ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-3-5-haiku-latest")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime or "image/png", "data": data_b64}},
            {"type": "text", "text": _question_prompt(question, "image")},
        ]}],
    }
    _, body = proxy.http_json("https://api.anthropic.com/v1/messages", payload,
                              {"x-api-key": key, "anthropic-version": "2023-06-01"})
    text = "".join(p.get("text", "") for p in body.get("content", []))
    return text, model


def _local_document(raw, mime, name):
    """Lecture locale des documents texte/PDF simples, sans dépendance externe."""
    text = ""
    if (mime or "").lower() == "application/pdf" or str(name).lower().endswith(".pdf"):
        # Extraction légère des chaînes lisibles dans un PDF (streams FlateDecode).
        import zlib
        chunks = []
        for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
            try:
                decoded = zlib.decompress(match.group(1))
            except Exception:
                decoded = match.group(1)
            chunks.append(decoded.decode("latin-1", "replace"))
        blob = "\n".join(chunks)
        for part in re.findall(r"\((?:[^()\\]|\\.)*\)", blob):
            chunks_txt = part[1:-1].replace("\\(", "(").replace("\\)", ")")
            if len(chunks_txt.strip()) > 1:
                text += chunks_txt + " "
    else:
        text = raw.decode("utf-8", "replace")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:30000]


def analyze(payload):
    """Analyse un fichier et retourne un rapport structuré + mission suggérée."""
    name = str(payload.get("name") or "fichier").strip()[:180]
    mime = str(payload.get("mime") or "").strip()[:120]
    content_b64 = str(payload.get("content") or "").strip()
    if not content_b64:
        raise ValueError("Contenu du fichier vide")
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except Exception:
        raise ValueError("Contenu du fichier invalide (base64 attendu)")
    if not raw:
        raise ValueError("Fichier vide")
    if len(raw) > MAX_BYTES:
        raise ValueError("Fichier trop volumineux (20 Mo maximum)")

    company = str(payload.get("company") or "").strip()[:120]
    project = str(payload.get("project") or "").strip()[:120]
    folder = str(payload.get("folder") or "Médias").strip()[:80]
    question = str(payload.get("question") or "").strip()[:1200]
    kind = kind_of(mime, name)
    providers = proxy.configured_providers()
    chosen = str(payload.get("provider") or "auto").lower()
    if chosen not in ("auto", "openai", "gemini", "anthropic"):
        chosen = "auto"

    # 1) Classer le fichier dans le dossier avant analyse.
    meta = files.upload(company, project, folder, name, content_b64, mime or "application/octet-stream", "multimedia")

    # 2) Choisir le moteur d'analyse disponible.
    text, engine, details_override = "", "", []

    def pick(*names):
        if chosen != "auto":
            return chosen if providers.get(chosen) else ""
        for n in names:
            if providers.get(n):
                return n
        return ""

    try:
        if kind == "document":
            local = _local_document(raw, mime, name)
            engine = "local"
            text = local or "Document binaire : aucun texte extractible localement."
            details_override = ["Texte extrait localement : " + str(len(text)) + " caractères."]
            # Un document riche peut être complété par un IA texte.
            text_provider = pick("gemini", "openai", "anthropic", "perplexity")
            if text_provider and len(local) < 30000:
                result = proxy.run_ai({
                    "provider": text_provider,
                    "prompt": _question_prompt(question, "document") +
                              "\n\nContenu du document :\n" + local[:18000],
                    "system": SYSTEM_PROMPT, "maxTokens": 2200,
                })
                text = result.get("text", "") or text
                engine = text_provider
        elif kind == "audio":
            if providers.get("openai"):
                text, details_override = _openai_transcribe(raw, name, mime)
                engine = "openai-whisper"
                # La transcription est structurée ensuite par le modèle texte.
                struct = pick("gemini", "openai", "anthropic")
                if struct and text:
                    result = proxy.run_ai({
                        "provider": struct,
                        "prompt": _question_prompt(question, "audio") + "\n\nTranscription :\n" + text[:15000],
                        "system": SYSTEM_PROMPT, "maxTokens": 2200,
                    })
                    text = result.get("text", "") or text
                    engine += "+" + struct
            else:
                provider = pick("gemini")
                if not provider:
                    raise RuntimeError("Analyse audio impossible : connectez OpenAI (Whisper) ou Gemini.")
                text, engine = _gemini_multimodal(content_b64, mime or "audio/mpeg", "audio", question)
        elif kind == "image":
            provider = pick("gemini", "openai", "anthropic")
            if not provider:
                raise RuntimeError("Analyse d'image impossible : connectez Gemini, OpenAI ou Claude.")
            if provider == "gemini":
                text, engine = _gemini_multimodal(content_b64, mime or "image/png", "image", question)
            elif provider == "openai":
                text, engine = _openai_vision(content_b64, mime or "image/png", question)
            else:
                text, engine = _anthropic_vision(content_b64, mime or "image/png", question)
        elif kind == "video":
            provider = pick("gemini")
            if not provider:
                raise RuntimeError("Analyse vidéo impossible : connectez Gemini (compréhension vidéo native).")
            text, engine = _gemini_multimodal(content_b64, mime or "video/mp4", "vidéo", question)
        else:
            raise RuntimeError("Type de fichier non pris en charge pour l'analyse : " + (mime or name))

        parsed = _json_from_text(text)
        if parsed is None:
            # Certains fournisseurs répondent en prose : on tente une structuration.
            struct = pick("gemini", "openai", "anthropic", "perplexity")
            if struct and len(text) < 24000:
                try:
                    result = proxy.run_ai({
                        "provider": struct,
                        "prompt": "Transforme l'analyse suivante en JSON strict selon cette consigne :\n" +
                                  SYSTEM_PROMPT + "\n\nAnalyse :\n" + text[:16000],
                        "system": "Réponds uniquement avec un objet JSON valide.", "maxTokens": 1600,
                    })
                    parsed = _json_from_text(result.get("text", ""))
                except Exception:
                    parsed = None
        report = _normalize(parsed, text)
        if details_override and not report["details"]:
            report["details"] = details_override
        report["summary"] = report["summary"] or ("Fichier " + kind + " analysé : " + name)
    except Exception as e:
        report = _normalize(None, "")
        report["summary"] = "Analyse indisponible : " + str(e)[:400]
        report["details"] = [str(e)[:400]]
        report["confidence"] = "faible"
        report["error"] = str(e)[:500]

    report.update({
        "ok": True, "kind": kind, "file": meta, "engine": engine,
        "name": name, "mime": mime, "company": company, "project": project,
        "analysedAt": proxy.now_iso(),
    })
    # 3) Enregistrer le rapport dans le dossier pour qu'il soit lu par les agents.
    md = _report_markdown(report)
    saved = files.save_text(company, project, "IA-analyse",
                            date.today().isoformat() + "-" + re.sub(r"[^\w\-]", "_", name)[:50] + ".md",
                            md, engine or "local")
    report["analysisFile"] = saved["path"]
    return report


def _report_markdown(report):
    lines = ["# Analyse multimédia · " + str(report.get("name", "")), "",
             "Fichier classé : " + str((report.get("file") or {}).get("path", "")),
             "Type : " + str(report.get("kind", "")) + " · Moteur : " + str(report.get("engine", "")),
             "Date : " + str(report.get("analysedAt", "")), "",
             "## Synthèse", str(report.get("summary", "")), "", "## Faits observés"]
    for item in report.get("details", []):
        lines.append("- " + str(item))
    lines += ["", "## Entités"]
    for key, values in (report.get("entities") or {}).items():
        if values:
            lines.append("- " + key + " : " + ", ".join(str(v) for v in values))
    lines += ["", "## Mission suggérée", str(report.get("suggestedMission", "")),
              "", "## Confiance", str(report.get("confidence", ""))]
    if report.get("error"):
        lines += ["", "## Incident", str(report["error"])]
    lines += ["", "## Analyse brute", "```", str(report.get("raw", ""))[:12000], "```"]
    return "\n".join(lines)


def mission_from_report(report, payload=None):
    """Construit le contexte de mission à partir d'un rapport d'analyse."""
    payload = payload or {}
    entities = report.get("entities") or {}
    signals = []
    for key in ("names", "organisations", "phones", "emails", "dates", "amounts", "urls"):
        vals = entities.get(key) or []
        if vals:
            signals.append(key + " : " + ", ".join(str(v) for v in vals[:6]))
    return {
        "company": str(payload.get("company") or report.get("company") or "").strip()[:120],
        "project": str(payload.get("project") or report.get("project") or "").strip()[:120],
        "topic": str(payload.get("topic") or report.get("suggestedMission") or
                     "Créer une mission à partir de l'analyse du fichier " + str(report.get("name", "")))[:1500],
        "research": ("Analyse du fichier " + str(report.get("name", "")) + " (" + str(report.get("kind", "")) + ")\n" +
                     str(report.get("summary", "")) + "\n\nFaits :\n- " +
                     "\n- ".join(str(d) for d in report.get("details", [])[:20]) +
                     ("\n\nSignaux :\n" + "\n".join(signals) if signals else "") +
                     "\n\nMission suggérée : " + str(report.get("suggestedMission", "")))[:30000],
        "publish": bool(payload.get("publish")),
    }
