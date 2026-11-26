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
    FACEBOOK_ACCESS_TOKEN / FACEBOOK_PAGE_ID / FACEBOOK_APP_ID / FACEBOOK_APP_SECRET
    INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID / INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET
    LINKEDIN_ACCESS_TOKEN / LINKEDIN_ORG_ID / LINKEDIN_PERSON_ID
    LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET
    X_ACCESS_TOKEN / X_USER_ID / X_CLIENT_ID / X_CLIENT_SECRET
    PUBLIC_BASE_URL       (utilisé pour construire les URI de callback OAuth)
    HOST / PORT           (défaut : 0.0.0.0:8000)

Endpoints :
    GET  /api/status, /api/robots, /api/agents, /api/catalog, /api/files
    GET  /api/google/callback, /api/oauth/callback  (callbacks publics OAuth)
    POST /api/ai, /api/publish, /api/robots/run
    POST /api/credentials, /api/catalog  (catalogue synchronisé prix/images)
    POST /api/agents, /api/pipeline/run, /api/files/upload
    POST /api/media/analyze, /api/media/mission  (analyse multimédia par IA)
    GET  /api/google/status, /api/google/auth-url, /api/google/backups
    GET  /api/oauth/providers, /api/oauth/auth-url
    POST /api/oauth/disconnect
    POST /api/google/sync, /api/google/restore
    GET  /api/messages, /api/messages/config, /api/messages/file/<nom>  (messagerie publique)
    POST /api/messages, /api/messages/subscribe  (messagerie et notifications push)
"""

import hmac
import html
import json
import os
import re
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
        "ALLOWED_ORIGINS", ALLOWED_ORIGIN + ",http://localhost:8086,http://127.0.0.1:8086,app://-"
    ).split(",") if o.strip() and o.strip() != "null"
}
PROXY_TOKEN = os.environ.get("TUS_PROXY_TOKEN", "").strip()
MAX_BODY = 12 * 1024 * 1024  # 8 Mo de pièce jointe en base64 + marge
_CACHES = {}
_CACHE_LOCK = threading.Lock()


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def cached(key, producer, ttl=30):
    """Évite les dérivations PBKDF2 et les appels réseau sur /api/status."""
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHES.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    value = producer()
    with _CACHE_LOCK:
        _CACHES[key] = (now, value)
    return value


IP_RATE = {}
IP_RATE_LOCK = threading.Lock()
AI_QUOTA = {}
AI_QUOTA_LIMIT = 2


def ai_quota_ok(ip, admin=False):
    """Deux essais IA distants par jour et par visiteur, appliqués côté serveur."""
    if admin:
        return True
    day = time.strftime("%Y-%m-%d")
    now = time.monotonic()
    with IP_RATE_LOCK:
        for key, value in list(AI_QUOTA.items()):
            if value[0] != day or now - value[2] > 86400:
                AI_QUOTA.pop(key, None)
        entry = AI_QUOTA.get(ip, (day, 0, now))
        if entry[1] >= AI_QUOTA_LIMIT:
            AI_QUOTA[ip] = entry
            return False
        AI_QUOTA[ip] = (day, entry[1] + 1, now)
        return True


def messages_rate_ok(ip, path, limit=120, window=600):
    """Limite globale par adresse IP, en plus du quota par conversation."""
    now = time.monotonic()
    with IP_RATE_LOCK:
        for key, hits in list(IP_RATE.items()):
            if not hits or now - hits[-1] > window:
                IP_RATE.pop(key, None)
        key = (ip, path)
        hits = IP_RATE.setdefault(key, [])
        hits[:] = [t for t in hits if now - t <= window]
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def now_iso():
    return datetime.now().isoformat(timespec="seconds")

MODELS = {
    "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "gemini": os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
    "perplexity": os.environ.get("PERPLEXITY_MODEL", "sonar"),
}


def configured_providers():
    def build():
        import vault
        return {
            "openai": vault.has("openai_api_key", "OPENAI_API_KEY"),
            "gemini": vault.has("gemini_api_key", "GEMINI_API_KEY"),
            "anthropic": vault.has("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "perplexity": vault.has("perplexity_api_key", "PERPLEXITY_API_KEY"),
        }
    return cached("providers", build)


def configured_networks():
    def build():
        import vault
        return {
            "facebook": vault.has("facebook_token", "FACEBOOK_ACCESS_TOKEN") and
                        vault.has("facebook_page", "FACEBOOK_PAGE_ID"),
            "instagram": vault.has("instagram_token", "INSTAGRAM_ACCESS_TOKEN") and
                         vault.has("instagram_user", "INSTAGRAM_USER_ID"),
            "linkedin": vault.has("linkedin_token", "LINKEDIN_ACCESS_TOKEN") and
                        (vault.has("linkedin_person", "LINKEDIN_PERSON_ID") or
                         vault.has("linkedin_org", "LINKEDIN_ORG_ID")),
            "x": vault.has("x_token", "X_ACCESS_TOKEN") and vault.has("x_user", "X_USER_ID"),
        }
    return cached("networks", build)


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
        # Le corps d'une erreur upstream peut contenir des secrets ou du HTML :
        # il est journalisé côté serveur, jamais renvoyé au navigateur.
        raw = e.read().decode("utf-8", "replace")[:1000]
        print("HTTP amont %s : %s" % (e.code, raw.replace("\n", " ")[:300]), file=sys.stderr, flush=True)
        raise RuntimeError("Service distant indisponible (HTTP %s)" % e.code) from e


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
        + ":generateContent"
    )
    _, body = http_json(url, {"contents": [{"parts": parts}]}, {"x-goog-api-key": key})
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
        person = _secret("linkedin_person", "LINKEDIN_PERSON_ID")
        org = _secret("linkedin_org", "LINKEDIN_ORG_ID")
        author = ("urn:li:person:" + person) if person else ("urn:li:organization:" + org)
        payload = {
            "author": author,
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

    if network == "x":
        token = _secret("x_token", "X_ACCESS_TOKEN")
        status, body = http_json(
            "https://api.x.com/2/tweets",
            {"text": text},
            {"Authorization": "Bearer " + token},
        )
        return {"ok": True, "network": network, "id": (body.get("data") or {}).get("id"), "status": status}

    raise ValueError("Réseau non pris en charge : " + network)


SECRET_KEYS = {
    "openai": "openai_api_key", "gemini": "gemini_api_key",
    "anthropic": "anthropic_api_key", "perplexity": "perplexity_api_key",
    "facebook": "facebook_token", "facebook_page": "facebook_page",
    "facebook_app_id": "facebook_app_id", "facebook_app_secret": "facebook_app_secret",
    "instagram": "instagram_token", "instagram_user": "instagram_user",
    "instagram_app_id": "instagram_app_id", "instagram_app_secret": "instagram_app_secret",
    "linkedin": "linkedin_token", "linkedin_org": "linkedin_org",
    "linkedin_person": "linkedin_person",
    "linkedin_client_id": "linkedin_client_id", "linkedin_client_secret": "linkedin_client_secret",
    "x": "x_token", "x_user": "x_user",
    "x_client_id": "x_client_id", "x_client_secret": "x_client_secret",
    "google_client_id": "google_client_id", "google_client_secret": "google_client_secret",
    "google_redirect_uri": "google_redirect_uri",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TouchUniqueProxy/3.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def _public_base(self):
        # PUBLIC_BASE_URL est la seule source de confiance en production. Les
        # en-têtes X-Forwarded-* fournis par un client ne peuvent pas détourner
        # l'URI de callback OAuth.
        configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if configured and re.match(r"^https://", configured):
            return configured
        host = (self.headers.get("Host") or "localhost:8000").split(",")[0].strip()
        if host.startswith("localhost") or host.startswith("127.0.0.1"):
            return "http://" + host
        return configured if configured.startswith("https://") else ""

    def _cors_origin(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin in ALLOWED_ORIGINS:
            return origin
        return ALLOWED_ORIGIN

    def _headers(self, status=200, content_type=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tus-Key, X-Tus-Thread")
        self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content_type and content_type.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                             "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, obj, status=200, extra=None):
        self._headers(status, extra=extra)
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _html(self, page, status=200):
        self._headers(status, "text/html; charset=utf-8")
        self.wfile.write(page.encode("utf-8"))

    def _bytes(self, content, mime, status=200, extra=None):
        self._headers(status, mime, extra)
        self.wfile.write(content)

    def _is_admin(self):
        supplied = self.headers.get("X-Tus-Key") or ""
        return bool(PROXY_TOKEN and hmac.compare_digest(supplied, PROXY_TOKEN))

    def _authorized(self):
        # Sans clé partagée, aucune route administrative n'est accessible.
        if not PROXY_TOKEN:
            self._send({"ok": False, "error": "Serveur non configuré : TUS_PROXY_TOKEN manquant."}, 503)
            return False
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin not in ALLOWED_ORIGINS:
            self._send({"ok": False, "error": "Origine non autorisée"}, 403)
            return False
        if not self._is_admin():
            self._send({"ok": False, "error": "Clé proxy invalide"}, 401)
            return False
        return True

    def _client_ip(self):
        return self.client_address[0] if self.client_address else ""

    def _cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return ""

    def _nonce_cookie(self, name, value):
        return {"Set-Cookie": "%s=%s; Path=/; HttpOnly; SameSite=Lax%s" % (
            name, value, "; Secure" if os.environ.get("PUBLIC_BASE_URL", "").startswith("https://") else "")}

    def do_OPTIONS(self):
        self._headers(204)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        # Le statut public et les callbacks OAuth doivent rester accessibles sans
        # jeton partagé ; tous les autres GET exposent des données ou des liens sensibles.
        public_gets = ("/api/status", "/api/oauth/providers", "/api/google/callback", "/api/oauth/callback",
                       "/api/messages/config", "/api/messages")
        public_get = path in public_gets or path.startswith("/api/messages/file/")
        if not public_get and not self._authorized():
            return
        try:
            if path == "/api/status":
                import messages
                # Le statut public ne révèle ni.email Google, ni compteurs, ni URI.
                # L'administrateur (clé valide) reçoit le tableau complet.
                payload = {
                    "ok": True,
                    "configured": True,
                    "ai": configured_providers(),
                    "social": configured_networks(),
                    "messages": {"ok": True, "enabled": messages.config()["enabled"]},
                    "version": 4,
                }
                if self._is_admin():
                    import google, oauth
                    base = self._public_base()
                    payload.update({
                        "proxyTokenRequired": True,
                        "robots": env_flag("TUS_ROBOT_AUTORUN"),
                        "google": cached("google-status", google.status, 60),
                        "oauth": cached("oauth-overview", lambda: oauth.overview(base), 60),
                        "redirectUri": oauth.redirect_uri(base) if base else "",
                    })
                self._send(payload)
                return
            if path == "/api/oauth/providers":
                import oauth
                base = self._public_base()
                self._send({"ok": bool(base), "providers": cached(
                    "oauth-overview", lambda: oauth.overview(base), 60),
                    "redirectUri": oauth.redirect_uri(base) if base else ""})
                return
            if path == "/api/oauth/auth-url":
                import oauth
                provider = (query.get("provider") or [""])[0]
                origin = (query.get("origin") or ALLOWED_ORIGIN).rstrip("/")
                if origin not in ALLOWED_ORIGINS:
                    raise ValueError("Origine de retour non autorisée.")
                result = oauth.auth_url(provider, self._public_base(), self._cookie("tus_oauth_nonce"), origin)
                self._send(result, extra=self._nonce_cookie("tus_oauth_nonce", result["nonce"]))
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
                origin = (query.get("origin") or ALLOWED_ORIGIN).rstrip("/")
                if origin not in ALLOWED_ORIGINS:
                    raise ValueError("Origine de retour non autorisée.")
                result = google.auth_url(self._cookie("tus_google_nonce"), origin)
                self._send(result, extra=self._nonce_cookie("tus_google_nonce", result["nonce"]))
                return
            if path == "/api/oauth/callback":
                import oauth
                provider = (query.get("provider") or [""])[0]
                if provider not in oauth.PROVIDERS:
                    provider = ""
                code = (query.get("code") or [""])[0]
                state = (query.get("state") or [""])[0]
                error = (query.get("error") or [""])[0]
                nonce = self._cookie("tus_oauth_nonce")
                return_origin = oauth.state_origin(state)
                return_nonce = oauth.state_nonce(state)
                if return_origin not in ALLOWED_ORIGINS:
                    return_origin = ALLOWED_ORIGIN
                if error or not code:
                    message = str(query.get("error_description") or [error or "Code d’autorisation absent."])[0]
                    self._html(oauth.callback_html(False, provider, message, return_origin, return_nonce))
                else:
                    try:
                        label = oauth.exchange(provider, code, state, self._public_base(), nonce)
                        self._html(oauth.callback_html(True, provider,
                                   "Connexion réussie : " + str(label) + ". Vous pouvez fermer cette fenêtre.",
                                   return_origin, return_nonce))
                    except Exception as e:
                        print("OAuth :", type(e).__name__, str(e)[:200], file=sys.stderr, flush=True)
                        self._html(oauth.callback_html(False, provider, "Connexion impossible, recommencez.",
                                                       return_origin, return_nonce))
                return
            if path == "/api/google/callback":
                import google
                code = (query.get("code") or [""])[0]
                state = (query.get("state") or [""])[0]
                return_origin = google.state_origin(state)
                return_nonce = google.state_nonce(state)
                if return_origin not in ALLOWED_ORIGINS:
                    return_origin = ALLOWED_ORIGIN
                if not code:
                    self._html(google.callback_html(False, "Code Google absent.", return_origin, return_nonce))
                else:
                    try:
                        google.exchange(code, state, self._cookie("tus_google_nonce"))
                        self._html(google.callback_html(True,
                                   "Votre Google Drive est connecté. Vous pouvez fermer cette fenêtre.",
                                   return_origin, return_nonce))
                    except Exception as e:
                        print("Google :", type(e).__name__, str(e)[:200], file=sys.stderr, flush=True)
                        self._html(google.callback_html(False, "Connexion impossible, recommencez.",
                                                         return_origin, return_nonce))
                return
            if path == "/api/google/backups":
                import google
                self._send(google.backups())
                return
            if path == "/api/google/file":
                import google
                self._send({"ok": True, "data": google.download((query.get("id") or [""])[0])})
                return
            if path == "/api/messages/config":
                import messages
                self._send(messages.config())
                return
            if path == "/api/messages":
                import messages
                thread = (query.get("thread") or [""])[0]
                # Le jeton est accepté en en-tête (jamais dans l'URL : logs et
                # Referer). La query string reste supportée temporairement.
                token = self.headers.get("X-Tus-Thread") or (query.get("token") or [""])[0]
                admin = self._is_admin()
                if not admin and token != thread:
                    raise ValueError("Jeton de conversation invalide.")
                self._send(messages.listing(None if admin else thread,
                                            (query.get("since") or [None])[0], admin))
                return
            if path.startswith("/api/messages/file/"):
                import messages
                mime, content = messages.attachment(path.rsplit("/", 1)[-1])
                self._bytes(content, mime, extra={
                    "Content-Disposition": 'attachment; filename="piece-jointe"',
                    "Cache-Control": "no-store"})
                return
            self._send({"ok": False, "error": "Introuvable"}, 404)
        except (ValueError, KeyError) as e:
            self._send({"ok": False, "error": str(e)[:300]}, 400)
        except Exception as e:
            print("Erreur GET :", type(e).__name__, str(e)[:300], file=sys.stderr, flush=True)
            self._send({"ok": False, "error": "Erreur interne du serveur."}, 500)

    def do_POST(self):
        path = self.path.split("?")[0]
        # L'essai IA du visiteur reste public ; le quota est appliqué côté serveur.
        public_posts = ("/api/messages", "/api/messages/subscribe", "/api/ai")
        if path not in public_posts and not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                self._send({"ok": False, "error": "Requête trop volumineuse."}, 413)
                return
            raw = self.rfile.read(length).decode("utf-8-sig").lstrip("\ufeff") or "{}"
            data = json.loads(raw) if length else {}
            if not isinstance(data, dict):
                raise ValueError("Requête invalide.")
            if path in public_posts and not messages_rate_ok(self._client_ip(), path):
                self._send({"ok": False, "error": "Trop de requêtes. Réessayez dans quelques minutes."}, 429)
                return
            if path == "/api/ai":
                if not ai_quota_ok(self._client_ip(), self._is_admin()):
                    raise ValueError("Vos 2 essais IA gratuits du jour sont utilisés. Demandez un accès complet sur WhatsApp.")
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
            if path == "/api/oauth/disconnect":
                import oauth
                provider = str(data.get("provider") or "").strip()
                if provider not in oauth.PROVIDERS:
                    raise ValueError("Réseau inconnu : " + provider)
                oauth.disconnect(provider)
                self._send({"ok": True, "provider": provider, "social": configured_networks()})
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
            if path == "/api/messages":
                import messages
                payload = dict(data)
                payload["admin"] = bool(data.get("admin")) and self._is_admin()
                payload["_ip"] = self._client_ip()
                self._send(messages.post(payload))
                return
            if path == "/api/messages/subscribe":
                import messages
                payload = dict(data)
                payload["role"] = "admin" if (data.get("role") == "admin" and self._is_admin()) else "client"
                payload["_ip"] = self._client_ip()
                self._send(messages.subscribe(payload))
                return
            self._send({"ok": False, "error": "Introuvable"}, 404)
        except (ValueError, KeyError) as e:
            self._send({"ok": False, "error": str(e)[:300]}, 400)
        except RuntimeError as e:
            print("Erreur amont :", str(e)[:300], file=sys.stderr, flush=True)
            self._send({"ok": False, "error": "Service distant indisponible."}, 502)
        except Exception as e:  # pragma: no cover
            print("Erreur POST :", type(e).__name__, str(e)[:300], file=sys.stderr, flush=True)
            self._send({"ok": False, "error": "Erreur interne du serveur."}, 500)


def robot_scheduler():
    """Exécute les robots une fois par jour, en mode simulation par défaut."""
    import robots
    floor = int(os.environ.get("TUS_ROBOT_HOUR", "0"))
    publish = env_flag("TUS_ROBOT_PUBLISH")
    while True:
        try:
            now = datetime.now()
            ids = robots.due(now.hour) if now.hour >= floor else []
            if ids:
                print("Robots : exécution quotidienne", ids, "publication=", publish, flush=True)
                results = [robots.run_robot(rid, dry=not publish) for rid in ids]
                state = robots.read_state()
                state["_lastDay"] = now.date().isoformat()
                robots.write_state(state)
                print("Robots :", [(r.get("id"), r.get("ok"), r.get("result", "")) for r in results], flush=True)
        except Exception as e:
            print("Robots : erreur", type(e).__name__, str(e)[:200], flush=True)
        time.sleep(60)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    if not PROXY_TOKEN:
        print("ATTENTION : TUS_PROXY_TOKEN absent. Toutes les routes administrateur sont refusées.",
              file=sys.stderr, flush=True)
    if not os.environ.get("PUBLIC_BASE_URL"):
        print("ATTENTION : PUBLIC_BASE_URL absent. Les callbacks OAuth ne peuvent pas être construits.",
              file=sys.stderr, flush=True)
    server = Server((host, port), Handler)
    print("Proxy Touch Unique sur http://%s:%s" % (host, port), flush=True)
    print("IA :", configured_providers(), flush=True)
    print("Réseaux :", configured_networks(), flush=True)
    if env_flag("TUS_ROBOT_AUTORUN"):
        threading.Thread(target=robot_scheduler, daemon=True, name="tus-robots").start()
        print("Robots quotidiens activés à", str(os.environ.get("TUS_ROBOT_HOUR", "8")) + " h",
              "(simulation)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
