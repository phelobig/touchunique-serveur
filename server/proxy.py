# -*- coding: utf-8 -*-
"""
Touch Unique Studio — proxy sécurisé pour IA, réseaux sociaux et Google Drive.

Les clés API et les tokens sociaux ne sont JAMAIS envoyés au navigateur :
ils sont lus dans le coffre chiffré du serveur ou ses variables d'environnement.
L'application Windows (Electron) est autorisée en plus des origines HTTPS.

Démarrage :
    python server/proxy.py

Variables d'environnement :
    TUS_PROXY_TOKEN       (optionnel) clé partagée envoyée dans X-Tus-Key
    ALLOWED_ORIGIN        origine autorisée (défaut : https://phelobig.github.io)
    OPENAI_API_KEY        clé OpenAI
    OPENAI_MODEL          (défaut : gpt-4o-mini)
    GEMINI_API_KEY        clé Google Gemini
    GEMINI_MODEL          (défaut : gemini-1.5-flash)
    ANTHROPIC_API_KEY     clé Anthropic
    ANTHROPIC_MODEL       (défaut : claude-3-5-haiku-latest)
    PERPLEXITY_API_KEY    clé Perplexity (recherche web)
    PERPLEXITY_MODEL      (défaut : sonar)
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
    TUS_VAULT_KEY         clé maître du coffre chiffré (sinon fichier .vault_key)
    ALLOWED_ORIGINS       origines autorisées, séparées par des virgules
    FACEBOOK_ACCESS_TOKEN / FACEBOOK_PAGE_ID
    INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID
    LINKEDIN_ACCESS_TOKEN / LINKEDIN_ORG_ID
    HOST / PORT           (défaut : 0.0.0.0:8000)

Endpoints :
    GET  /api/status, /api/robots, /api/agents, /api/catalog, /api/files, /api/google/callback
    POST /api/ai, /api/publish, /api/robots/run
    POST /api/credentials, /api/catalog  (catalogue synchronisé prix/images)
    POST /api/agents, /api/pipeline/run, /api/files/upload
    POST /api/media/analyze, /api/media/mission  (analyse multimédia par IA)
    GET  /api/google/status, /api/google/auth-url, /api/google/backups
    POST /api/google/sync, /api/google/restore
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://phelobig.github.io").rstrip("/")
ALLOWED_ORIGINS = {
    o.strip().rstrip("/") for o in os.environ.get(
        "ALLOWED_ORIGINS", ALLOWED_ORIGIN + ",http://localhost:8086,http://127.0.0.1:8086,app://-,file://"
    ).split(",") if o.strip()
}
PROXY_TOKEN = os.environ.get("TUS_PROXY_TOKEN", "").strip()


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")

MODELS = {
    "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "gemini": os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
    "perplexity": os.environ.get("PERPLEXITY_MODEL", "sonar"),
}


def configured_providers():
    import vault
    return {
        "openai": vault.has("openai_api_key", "OPENAI_API_KEY"),
        "gemini": vault.has("gemini_api_key", "GEMINI_API_KEY"),
        "anthropic": vault.has("anthropic_api_key", "ANTHROPIC_API_KEY"),
        "perplexity": vault.has("perplexity_api_key", "PERPLEXITY_API_KEY"),
    }


def configured_networks():
    import vault
    return {
        "facebook": vault.has("facebook_token", "FACEBOOK_ACCESS_TOKEN") and
                    vault.has("facebook_page", "FACEBOOK_PAGE_ID"),
        "instagram": vault.has("instagram_token", "INSTAGRAM_ACCESS_TOKEN") and
                     vault.has("instagram_user", "INSTAGRAM_USER_ID"),
        "linkedin": vault.has("linkedin_token", "LINKEDIN_ACCESS_TOKEN") and
                    vault.has("linkedin_org", "LINKEDIN_ORG_ID"),
    }


def http_json(url, payload=None, headers=None, method=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} : {raw[:600]}") from e


def _secret(name, env_name=None):
    import vault
    return vault.secret(name, env_name)


def call_openai(prompt, system, max_tokens):
    key = _secret("openai_api_key", "OPENAI_API_KEY")
    payload = {
        "model": MODELS["openai"],
        "max_tokens": max_tokens,
        "messages": ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ],
    }
    _, body = http_json(
        "https://api.openai.com/v1/chat/completions",
        payload,
        {"Authorization": "Bearer " + key},
    )
    return body["choices"][0]["message"]["content"], MODELS["openai"]


def call_gemini(prompt, system, max_tokens):
    key = _secret("gemini_api_key", "GEMINI_API_KEY")
    parts = []
    if system:
        parts.append({"text": "Consigne : " + system + "\n\n"})
    parts.append({"text": prompt})
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + MODELS["gemini"]
        + ":generateContent?key="
        + urllib.parse.quote(key, safe="")
    )
    _, body = http_json(url, {"contents": [{"parts": parts}]})
    candidates = body.get("candidates") or []
    text = candidates[0]["content"]["parts"][0].get("text", "") if candidates else ""
    return text, MODELS["gemini"]


def call_anthropic(prompt, system, max_tokens):
    key = _secret("anthropic_api_key", "ANTHROPIC_API_KEY")
    payload = {
        "model": MODELS["anthropic"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    _, body = http_json(
        "https://api.anthropic.com/v1/messages",
        payload,
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return "".join(p.get("text", "") for p in body.get("content", [])), MODELS["anthropic"]


def call_perplexity(prompt, system, max_tokens):
    """Perplexity : recherche web réelle avec citations dans la réponse."""
    key = _secret("perplexity_api_key", "PERPLEXITY_API_KEY")
    payload = {
        "model": MODELS["perplexity"],
        "max_tokens": max_tokens,
        "messages": ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ],
        "return_citations": True,
    }
    _, body = http_json(
        "https://api.perplexity.ai/chat/completions",
        payload,
        {"Authorization": "Bearer " + key},
    )
    text = body["choices"][0]["message"]["content"]
    citations = body.get("citations") or []
    if citations:
        text += "\n\nSources :\n" + "\n".join("- " + str(u) for u in citations[:10])
    return text, MODELS["perplexity"]


def run_ai(data):
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Prompt vide")
    system = str(data.get("system") or "")[:2000]
    max_tokens = min(max(int(data.get("maxTokens") or 900), 64), 4096)
    provider = str(data.get("provider") or "auto").lower()
    providers = configured_providers()

    if provider == "auto":
        for name in ("perplexity", "openai", "gemini", "anthropic"):
            if providers[name]:
                provider = name
                break
    if provider not in providers or not providers.get(provider):
        raise ValueError("Fournisseur IA non connecté : " + provider)

    funcs = {"openai": call_openai, "gemini": call_gemini,
             "anthropic": call_anthropic, "perplexity": call_perplexity}
    text, model = funcs[provider](prompt, system, max_tokens)
    return {"ok": True, "provider": provider, "model": model, "text": text}


def run_publish(data):
    network = str(data.get("network") or "").lower()
    text = str(data.get("text") or "").strip()
    image_url = str(data.get("imageUrl") or "").strip()
    if not text:
        raise ValueError("Texte vide")

    if network == "facebook":
        token = _secret("facebook_token", "FACEBOOK_ACCESS_TOKEN")
        page = _secret("facebook_page", "FACEBOOK_PAGE_ID")
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{page}/photos"
            status, body = http_json(url, {"url": image_url, "message": text, "access_token": token}, method="POST")
        else:
            url = f"https://graph.facebook.com/v19.0/{page}/feed"
            status, body = http_json(url, {"message": text, "access_token": token}, method="POST")
        return {"ok": True, "network": network, "id": body.get("id") or body.get("post_id"), "status": status}

    if network == "instagram":
        if not image_url:
            raise ValueError("Instagram nécessite une URL d'image publique")
        token = _secret("instagram_token", "INSTAGRAM_ACCESS_TOKEN")
        user = _secret("instagram_user", "INSTAGRAM_USER_ID")
        _, media = http_json(
            f"https://graph.facebook.com/v19.0/{user}/media",
            {"image_url": image_url, "caption": text, "access_token": token},
            method="POST",
        )
        creation_id = media.get("id")
        if not creation_id:
            raise ValueError("Création média Instagram impossible")
        _, body = http_json(
            f"https://graph.facebook.com/v19.0/{user}/media_publish",
            {"creation_id": creation_id, "access_token": token},
            method="POST",
        )
        return {"ok": True, "network": network, "id": body.get("id"), "status": 200}

    if network == "linkedin":
        token = _secret("linkedin_token", "LINKEDIN_ACCESS_TOKEN")
        org = _secret("linkedin_org", "LINKEDIN_ORG_ID")
        payload = {
            "author": "urn:li:organization:" + org,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        status, body = http_json(
            "https://api.linkedin.com/v2/ugcPosts",
            payload,
            {"Authorization": "Bearer " + token, "X-Restli-Protocol-Version": "2.0.0"},
        )
        return {"ok": True, "network": network, "id": body.get("id"), "status": status}

    raise ValueError("Réseau non pris en charge : " + network)


SECRET_KEYS = {
    "openai": "openai_api_key", "gemini": "gemini_api_key",
    "anthropic": "anthropic_api_key", "perplexity": "perplexity_api_key",
    "facebook": "facebook_token", "facebook_page": "facebook_page",
    "instagram": "instagram_token", "instagram_user": "instagram_user",
    "linkedin": "linkedin_token", "linkedin_org": "linkedin_org",
    "google_client_id": "google_client_id", "google_client_secret": "google_client_secret",
    "google_redirect_uri": "google_redirect_uri",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TouchUniqueProxy/2.0"

    def _cors_origin(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin in ALLOWED_ORIGINS or origin in ("null", "file://"):
            return origin or ALLOWED_ORIGIN
        return ALLOWED_ORIGIN

    def _headers(self, status=200, content_type=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tus-Key")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def _send(self, obj, status=200):
        self._headers(status)
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _html(self, page, status=200):
        self._headers(status, "text/html; charset=utf-8")
        self.wfile.write(page.encode("utf-8"))

    def _authorized(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin not in ALLOWED_ORIGINS and origin not in ("null", "file://"):
            self._send({"ok": False, "error": "Origine non autorisée"}, 403)
            return False
        if PROXY_TOKEN and self.headers.get("X-Tus-Key") != PROXY_TOKEN:
            self._send({"ok": False, "error": "Clé proxy invalide"}, 401)
            return False
        return True

    def do_OPTIONS(self):
        self._headers(204)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        # Le statut public et le callback Google doivent rester accessibles sans
        # jeton partagé ; tous les autres GET exposent des données ou des liens sensibles.
        if path not in ("/api/status", "/api/google/callback") and not self._authorized():
            return
        try:
            if path == "/api/status":
                import google
                self._send({
                    "ok": True,
                    "ai": configured_providers(),
                    "social": configured_networks(),
                    "proxyTokenRequired": bool(PROXY_TOKEN),
                    "robots": env_flag("TUS_ROBOT_AUTORUN"),
                    "google": google.status(),
                    "version": 2,
                })
                return
            if path == "/api/robots":
                import robots
                self._send(robots.overview())
                return
            if path == "/api/agents":
                import pipeline
                self._send(pipeline.overview())
                return
            if path == "/api/catalog":
                import catalog
                self._send(catalog.status())
                return
            if path == "/api/files":
                import files
                self._send({"ok": True, "files": files.listing(
                    (query.get("company") or [None])[0],
                    (query.get("project") or [None])[0],
                    (query.get("folder") or [None])[0])})
                return
            if path == "/api/files/download":
                import files
                meta, content = files.download((query.get("id") or [""])[0])
                self._send({"ok": True, "meta": meta, "content": content})
                return
            if path == "/api/google/status":
                import google
                self._send(google.status())
                return
            if path == "/api/google/auth-url":
                import google
                self._send(google.auth_url())
                return
            if path == "/api/google/callback":
                import google
                code = (query.get("code") or [""])[0]
                state = (query.get("state") or [""])[0]
                if not code:
                    self._html(google.callback_html(False, "Code Google absent."))
                else:
                    try:
                        google.exchange(code, state)
                        self._html(google.callback_html(True, "Votre Google Drive est connecté. Vous pouvez fermer cette fenêtre."))
                    except Exception as e:
                        self._html(google.callback_html(False, str(e)[:300]))
                return
            if path == "/api/google/backups":
                import google
                self._send(google.backups())
                return
            if path == "/api/google/file":
                import google
                self._send({"ok": True, "data": google.download((query.get("id") or [""])[0])})
                return
            self._send({"ok": False, "error": "Introuvable"}, 404)
        except (ValueError, KeyError, RuntimeError) as e:
            self._send({"ok": False, "error": str(e)[:600]}, 400)
        except Exception as e:
            self._send({"ok": False, "error": "Erreur interne : " + type(e).__name__ + " : " + str(e)[:300]}, 500)

    def do_POST(self):
        if not self._authorized():
            return
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
            if path == "/api/ai":
                self._send(run_ai(data))
                return
            if path == "/api/publish":
                self._send(run_publish(data))
                return
            if path == "/api/robots/run":
                import robots
                rid = str(data.get("id") or "all")
                dry = bool(data.get("dryRun"))
                out = robots.run_all(dry) if rid == "all" else robots.run_robot(rid, dry)
                self._send({"ok": True, "results": out} if rid == "all" else out)
                return
            if path == "/api/robots/config":
                import robots
                self._send({"ok": True, "config": robots.save_config(data.get("config") or [])})
                return
            if path == "/api/credentials":
                import vault
                name = str(data.get("name") or "").strip()
                value = str(data.get("value") or "").strip()
                if name not in SECRET_KEYS:
                    raise ValueError("Identifiant de connexion inconnu : " + name)
                if not value:
                    vault.delete("secrets", SECRET_KEYS[name])
                else:
                    vault.set("secrets", SECRET_KEYS[name], value)
                self._send({"ok": True, "ai": configured_providers(), "social": configured_networks()})
                return
            if path == "/api/pipeline/run":
                import pipeline
                self._send(pipeline.run_case(data))
                return
            if path == "/api/agents":
                import pipeline
                self._send({"ok": True, "agents": pipeline.save_config(data.get("agents") or [])})
                return
            if path == "/api/catalog":
                import catalog
                self._send({"ok": True, "catalog": catalog.write(data.get("catalog") or data)})
                return
            if path == "/api/files/upload":
                import files
                self._send({"ok": True, "file": files.upload(
                    data.get("company") or "", data.get("project") or "",
                    data.get("folder") or "Documents", data.get("name") or "",
                    data.get("content") or "", data.get("mime") or "", data.get("source") or "manuel")})
                return
            if path == "/api/files/delete":
                import files
                self._send({"ok": files.remove(str(data.get("id") or ""))})
                return
            if path == "/api/media/analyze":
                import media
                self._send(media.analyze(data))
                return
            if path == "/api/media/mission":
                import media, pipeline
                report = media.analyze(data)
                mission = media.mission_from_report(report, data)
                outcome = pipeline.run_case(mission)
                outcome["analysis"] = report
                outcome["mission"] = mission
                self._send(outcome)
                return
            if path == "/api/google/sync":
                import google
                self._send(google.sync(data))
                return
            if path == "/api/google/restore":
                import google
                self._send({"ok": True, "data": google.download(str(data.get("id") or ""))})
                return
            self._send({"ok": False, "error": "Introuvable"}, 404)
        except (ValueError, KeyError, RuntimeError) as e:
            self._send({"ok": False, "error": str(e)[:800]}, 400)
        except Exception as e:  # pragma: no cover
            self._send({"ok": False, "error": "Erreur interne : " + type(e).__name__ + " : " + str(e)[:300]}, 500)


def robot_scheduler():
    """Exécute les robots une fois par jour, sans intervention de l'utilisateur."""
    import robots
    floor = int(os.environ.get("TUS_ROBOT_HOUR", "0"))
    while True:
        try:
            now = datetime.now()
            ids = robots.due(now.hour) if now.hour >= floor else []
            if ids:
                print("Robots : exécution quotidienne", ids, flush=True)
                results = [robots.run_robot(rid) for rid in ids]
                state = robots.read_state()
                state["_lastDay"] = now.date().isoformat()
                robots.write_state(state)
                print("Robots :", [(r.get("id"), r.get("ok"), r.get("result", "")) for r in results], flush=True)
        except Exception as e:
            print("Robots : erreur", type(e).__name__, str(e)[:200], flush=True)
        time.sleep(60)


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print("Proxy Touch Unique sur http://%s:%s" % (host, port), flush=True)
    print("IA :", configured_providers(), flush=True)
    print("Réseaux :", configured_networks(), flush=True)
    if env_flag("TUS_ROBOT_AUTORUN"):
        threading.Thread(target=robot_scheduler, daemon=True, name="tus-robots").start()
        print("Robots quotidiens activés à", str(os.environ.get("TUS_ROBOT_HOUR", "8")) + " h", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
