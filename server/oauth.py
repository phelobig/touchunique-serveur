# -*- coding: utf-8 -*-
"""Connexions OAuth en un clic pour les réseaux sociaux.

Aucun secret n'est renvoyé au navigateur. Les identifiants d'application et
les jetons obtenus sont chiffrés dans le coffre du serveur. Le callback
redirige vers l'application avec un simple message postMessage, sans token.

Variables d'environnement ou coffre :
    FACEBOOK_APP_ID / FACEBOOK_APP_SECRET
    INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET  (repli sur Facebook)
    LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET
    X_CLIENT_ID / X_CLIENT_SECRET
    PUBLIC_BASE_URL  (ex. https://mon-serveur.onrender.com)
"""

import base64
import hashlib
import hmac
import html
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import vault

PROVIDERS = {
    "facebook": {
        "name": "Facebook",
        "hint": "Page Facebook branchée à l’application Meta",
        "console": "https://developers.facebook.com/apps/",
        "scopes": "pages_manage_posts,pages_read_engagement,public_profile,email",
        "authorize": "https://www.facebook.com/v19.0/dialog/oauth",
        "token": "https://graph.facebook.com/v19.0/oauth/access_token",
    },
    "instagram": {
        "name": "Instagram",
        "hint": "Compte Instagram professionnel lié à une page Facebook",
        "console": "https://developers.facebook.com/apps/",
        "scopes": "instagram_basic,instagram_content_publish,pages_show_list,pages_manage_posts",
        "authorize": "https://www.facebook.com/v19.0/dialog/oauth",
        "token": "https://graph.facebook.com/v19.0/oauth/access_token",
    },
    "linkedin": {
        "name": "LinkedIn",
        "hint": "Compte LinkedIn autorisé à publier",
        "console": "https://www.linkedin.com/developers/apps/",
        "scopes": "openid profile email w_member_social",
        "authorize": "https://www.linkedin.com/oauth/v2/authorization",
        "token": "https://www.linkedin.com/oauth/v2/accessToken",
    },
    "x": {
        "name": "X / Twitter",
        "hint": "Compte X autorisé à publier des tweets",
        "console": "https://developer.x.com/en/portal/dashboard",
        "scopes": "tweet.write users.read tweet.read offline.access",
        "authorize": "https://twitter.com/i/oauth2/authorize",
        "token": "https://api.x.com/2/oauth2/token",
    },
}

STATES = {}
STATE_TTL = 600


def _client(provider, kind, env_name):
    value = vault.secret(provider + "_" + kind, env_name)
    if provider == "instagram" and not value:
        value = vault.secret("facebook_" + kind, "FACEBOOK_" + kind.upper())
    return value


def credentials(provider):
    if provider in ("facebook", "instagram"):
        return (_client(provider, "app_id", "FACEBOOK_APP_ID" if provider == "facebook" else "INSTAGRAM_APP_ID"),
                _client(provider, "app_secret", "FACEBOOK_APP_SECRET" if provider == "facebook" else "INSTAGRAM_APP_SECRET"))
    if provider == "linkedin":
        return (_client(provider, "client_id", "LINKEDIN_CLIENT_ID"),
                _client(provider, "client_secret", "LINKEDIN_CLIENT_SECRET"))
    if provider == "x":
        return (_client(provider, "client_id", "X_CLIENT_ID"),
                _client(provider, "client_secret", "X_CLIENT_SECRET"))
    return "", ""


def configured(provider):
    cid, secret = credentials(provider)
    return bool(cid and secret)


def redirect_uri(base):
    return str(base or "").rstrip("/") + "/api/oauth/callback"


def _clean_states():
    now = time.time()
    for key, value in list(STATES.items()):
        if now - value.get("at", 0) > STATE_TTL:
            STATES.pop(key, None)
    while len(STATES) > 200:  # borne mémoire
        STATES.pop(next(iter(STATES)))


def _url_encode(params):
    return urllib.parse.urlencode(params)


def auth_url(provider, base, nonce="", origin=""):
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError("Réseau inconnu : " + str(provider))
    cid, _ = credentials(provider)
    if not cid:
        raise RuntimeError("Application " + cfg["name"] + " non configurée sur le serveur (Client ID / Secret).")
    _clean_states()
    state = secrets.token_urlsafe(24)
    cookie_nonce = nonce or secrets.token_urlsafe(24)
    record = {"at": time.time(), "provider": provider,
              "nonce": cookie_nonce, "origin": origin}
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(base),
        "response_type": "code",
        "state": state,
        "scope": cfg["scopes"],
    }
    if provider == "x":
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        record["verifier"] = verifier
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    STATES[state] = record
    return {"ok": True, "provider": provider, "name": cfg["name"],
            "state": state, "nonce": cookie_nonce, "origin": origin,
            "url": cfg["authorize"] + "?" + _url_encode(params)}


def _post_form(url, payload, headers=None):
    data = urllib.parse.urlencode(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except ValueError:
                return dict(urllib.parse.parse_qsl(raw))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("HTTP " + str(e.code) + " : " + raw) from e


def _get_json(url, token=None):
    hdrs = {"Accept": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _token_exchange(provider, code, state, base):
    cfg = PROVIDERS.get(provider)
    cid, secret = credentials(provider)
    if not cid or not secret:
        raise RuntimeError("Application " + cfg["name"] + " non configurée sur le serveur.")
    payload = {
        "client_id": cid,
        "client_secret": secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(base),
    }
    headers = None
    if provider == "x":
        verifier = state.pop("verifier", "")
        basic = base64.b64encode((cid + ":" + secret).encode("utf-8")).decode("ascii")
        payload = {"code": code, "grant_type": "authorization_code",
                   "redirect_uri": redirect_uri(base), "code_verifier": verifier}
        headers = {"Authorization": "Basic " + basic}
    return _post_form(cfg["token"], payload, headers)


def _facebook_pages(token, want_instagram):
    pages = _get_json(
        "https://graph.facebook.com/v19.0/me/accounts?fields=id,name,access_token,instagram_business_account&access_token="
        + urllib.parse.quote(token, safe=""),
    ).get("data") or []
    for page in pages:
        ig = page.get("instagram_business_account") or {}
        if want_instagram and ig.get("id"):
            return page.get("access_token") or token, str(ig["id"]), page.get("name", "Instagram")
    if not want_instagram and pages:
        page = pages[0]
        return page.get("access_token") or token, str(page.get("id", "")), page.get("name", "Facebook")
    return "", "", ""


def _store(provider, body):
    if provider in ("facebook", "instagram"):
        token = body.get("access_token", "")
        if not token:
            raise RuntimeError("Aucun jeton renvoyé par " + PROVIDERS[provider]["name"] + ".")
        if provider == "facebook":
            page_token, page_id, label = _facebook_pages(token, False)
            if not page_id:
                raise RuntimeError("Aucune page Facebook trouvée. Créez une page puis reconnectez-la.")
            vault.set("secrets", "facebook_token", page_token)
            vault.set("secrets", "facebook_page", page_id)
        else:
            page_token, ig_id, label = _facebook_pages(token, True)
            if not ig_id:
                raise RuntimeError("Aucun compte Instagram professionnel lié à une page Facebook.")
            vault.set("secrets", "instagram_token", page_token)
            vault.set("secrets", "instagram_user", ig_id)
        return label
    if provider == "linkedin":
        token = body.get("access_token", "")
        if not token:
            raise RuntimeError("Aucun jeton LinkedIn renvoyé.")
        info = _get_json("https://api.linkedin.com/v2/userinfo", token)
        person = str(info.get("sub") or "")
        if not person:
            raise RuntimeError("Identifiant LinkedIn introuvable.")
        vault.set("secrets", "linkedin_token", token)
        vault.set("secrets", "linkedin_person", person)
        return info.get("name") or "LinkedIn"
    if provider == "x":
        token = body.get("access_token", "")
        if not token:
            raise RuntimeError("Aucun jeton X renvoyé.")
        info = _get_json("https://api.x.com/2/users/me", token)
        user = ((info.get("data") or {}).get("id")) or ""
        if not user:
            raise RuntimeError("Identifiant X introuvable.")
        vault.set("secrets", "x_token", token)
        vault.set("secrets", "x_user", str(user))
        return (info.get("data") or {}).get("username") or "X"
    raise ValueError("Réseau inconnu : " + str(provider))


def state_origin(state):
    record = STATES.get(state or "")
    return str((record or {}).get("origin") or "")


def state_nonce(state):
    record = STATES.get(state or "")
    return str((record or {}).get("nonce") or "")


def exchange(provider, code, state, base, nonce=""):
    if provider not in PROVIDERS:
        raise ValueError("Réseau inconnu : " + str(provider))
    if not code:
        raise ValueError("Code d'autorisation absent.")
    _clean_states()
    record = STATES.pop(state, None) if state else None
    if not record or record.get("provider") != provider or time.time() - record.get("at", 0) > STATE_TTL:
        raise RuntimeError("État OAuth inconnu ou expiré : recommencez la connexion.")
    if not nonce or not record.get("nonce") or not hmac.compare_digest(str(nonce), str(record["nonce"])):
        raise RuntimeError("Session OAuth non reconnue : recommencez la connexion.")
    body = _token_exchange(provider, code, record, base)
    return _store(provider, body)


def connected(provider):
    keys = {
        "facebook": (("facebook_token", "FACEBOOK_ACCESS_TOKEN"), ("facebook_page", "FACEBOOK_PAGE_ID")),
        "instagram": (("instagram_token", "INSTAGRAM_ACCESS_TOKEN"), ("instagram_user", "INSTAGRAM_USER_ID")),
        "linkedin": (("linkedin_token", "LINKEDIN_ACCESS_TOKEN"), ("linkedin_person", "LINKEDIN_PERSON_ID")),
        "x": (("x_token", "X_ACCESS_TOKEN"), ("x_user", "X_USER_ID")),
    }.get(provider, ())
    return all(vault.has(name, env) for name, env in keys)


def disconnect(provider):
    keys = {
        "facebook": ["facebook_token", "facebook_page"],
        "instagram": ["instagram_token", "instagram_user"],
        "linkedin": ["linkedin_token", "linkedin_person", "linkedin_org"],
        "x": ["x_token", "x_user"],
    }.get(provider, [])
    for key in keys:
        vault.delete("secrets", key)
    return connected(provider)


def overview(base):
    out = []
    for provider, cfg in PROVIDERS.items():
        out.append({
            "id": provider,
            "name": cfg["name"],
            "hint": cfg["hint"],
            "console": cfg["console"],
            "configured": configured(provider),
            "connected": connected(provider),
            "connectedEnv": connected(provider),
            "redirectUri": redirect_uri(base),
        })
    return out


def _js(value):
    """Chaîne JavaScript sûre, même en contexte <script>."""
    return (json.dumps(str(value)[:300])
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("/", "\\u002f"))


def callback_html(ok, provider, message, origin="", nonce=""):
    color = "#0d6b39" if ok else "#a31127"
    label = PROVIDERS.get(provider, {}).get("name", "Réseau")
    target = _js(origin or "https://phelobig.github.io")
    nonce_js = _js(nonce)
    return """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Touch Unique — Connexion</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:16px system-ui;background:#fff8f6;color:#1c1013;display:grid;place-items:center;min-height:100vh;margin:0}
div{background:#fff;border:1px solid #e6ccd0;border-radius:16px;padding:28px;max-width:420px;text-align:center}
b{color:%s}button{margin-top:16px;padding:10px 18px;border:0;border-radius:10px;background:%s;color:#fff;cursor:pointer}</style></head>
<body><div><b>%s</b><p>%s</p><button onclick="window.close()">Fermer</button></div>
<script>try{if(window.opener)window.opener.postMessage({type:'tus-oauth',ok:%s,provider:%s,message:%s,nonce:%s},%s)}catch(e){}</script></body></html>""" % (
        color, color,
        html.escape("Connexion réussie" if ok else "Connexion impossible"),
        html.escape(str(message)[:300]),
        "true" if ok else "false",
        _js(provider), _js(message), nonce_js, target,
    )
