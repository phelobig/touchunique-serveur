# -*- coding: utf-8 -*-
"""Sauvegarde synchronisée sur le Google Drive de l'utilisateur (OAuth 2.0).

Variables d'environnement :
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
Les jetons sont conservés chiffrés dans le coffre du serveur.
"""

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

import vault

SCOPES = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/drive.file"
FOLDER = "TouchUniqueStudio"
STATES = {}


def setting(name, env_name):
    return vault.secret(name, env_name)


def configured():
    return bool(setting("google_client_id", "GOOGLE_CLIENT_ID") and
                setting("google_client_secret", "GOOGLE_CLIENT_SECRET") and
                setting("google_redirect_uri", "GOOGLE_REDIRECT_URI"))


def tokens():
    raw = vault.get("google", "tokens")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def auth_url():
    if not configured():
        raise RuntimeError("Google Drive non configuré sur le serveur (Client ID / Secret / URI de redirection).")
    state = secrets.token_urlsafe(24)
    STATES[state] = time.time()
    params = {
        "client_id": setting("google_client_id", "GOOGLE_CLIENT_ID"),
        "redirect_uri": setting("google_redirect_uri", "GOOGLE_REDIRECT_URI"),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"state": state, "url": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)}


def exchange(code, state=""):
    if state and state not in STATES:
        raise RuntimeError("État OAuth inconnu ou expiré")
    STATES.pop(state, None)
    payload = {
        "code": code,
        "client_id": setting("google_client_id", "GOOGLE_CLIENT_ID"),
        "client_secret": setting("google_client_secret", "GOOGLE_CLIENT_SECRET"),
        "redirect_uri": setting("google_redirect_uri", "GOOGLE_REDIRECT_URI"),
        "grant_type": "authorization_code",
    }
    body = _post_form("https://oauth2.googleapis.com/token", payload)
    vault.set("google", "tokens", json.dumps(body))
    return True


def _post_form(url, payload):
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _request(url, token, payload=None, method=None, headers=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if data:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def access_token():
    t = tokens()
    if not t:
        raise RuntimeError("Compte Google non connecté")
    if t.get("expiry", 0) > time.time() + 60 and t.get("access_token"):
        return t["access_token"]
    if not t.get("refresh_token"):
        raise RuntimeError("Session Google expirée : reconnectez le compte.")
    body = _post_form("https://oauth2.googleapis.com/token", {
        "client_id": setting("google_client_id", "GOOGLE_CLIENT_ID"),
        "client_secret": setting("google_client_secret", "GOOGLE_CLIENT_SECRET"),
        "refresh_token": t["refresh_token"],
        "grant_type": "refresh_token",
    })
    t.update(body)
    t["expiry"] = time.time() + int(body.get("expires_in", 3600))
    vault.set("google", "tokens", json.dumps(t))
    return t["access_token"]


def status():
    if not configured():
        return {"ok": False, "configured": False, "connected": False,
                "error": "Client ID / Secret Google à configurer sur le serveur."}
    if not tokens():
        return {"ok": True, "configured": True, "connected": False}
    try:
        info = _request("https://www.googleapis.com/oauth2/v3/userinfo", access_token())
        return {"ok": True, "configured": True, "connected": True, "email": info.get("email", "")}
    except Exception as e:
        return {"ok": False, "configured": True, "connected": False, "error": str(e)[:300]}


def _folder_id(token):
    query = urllib.parse.quote("mimeType='application/vnd.google-apps.folder' and name='" + FOLDER + "' and trashed=false")
    found = _request("https://www.googleapis.com/drive/v3/files?q=" + query, token)
    files = found.get("files") or []
    if files:
        return files[0]["id"]
    made = _request("https://www.googleapis.com/drive/v3/files", token, {
        "name": FOLDER, "mimeType": "application/vnd.google-apps.folder"})
    return made["id"]


def sync(payload):
    token = access_token()
    parent = _folder_id(token)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    name = "TouchUnique-sauvegarde-" + stamp + ".json"
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    boundary = "----TouchUniqueBoundary" + secrets.token_hex(8)
    metadata = json.dumps({"name": name, "parents": [parent], "mimeType": "application/json"}, ensure_ascii=False)
    multipart = (
        ("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + metadata +
         "\r\n--" + boundary + "\r\nContent-Type: application/json\r\n\r\n").encode("utf-8") +
        body + ("\r\n--" + boundary + "--\r\n").encode("utf-8")
    )
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
        data=multipart,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "multipart/related; boundary=" + boundary},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        created = json.loads(resp.read().decode("utf-8"))
    vault.set("google", "lastSync", {"at": datetime.now().isoformat(timespec="seconds"),
                                      "id": created.get("id"), "name": name})
    return {"ok": True, "id": created.get("id"), "name": name, "at": vault.get("google", "lastSync")["at"]}


def backups():
    token = access_token()
    parent = _folder_id(token)
    query = urllib.parse.quote("'" + parent + "' in parents and trashed=false")
    found = _request("https://www.googleapis.com/drive/v3/files?q=" + query + "&orderBy=createdTime desc&pageSize=30", token)
    return {"ok": True, "files": found.get("files", [])}


def download(file_id):
    token = access_token()
    req = urllib.request.Request(
        "https://www.googleapis.com/drive/v3/files/" + urllib.parse.quote(file_id) + "?alt=media",
        headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def callback_html(ok, message):
    color = "#0d6b39" if ok else "#a31127"
    return """<!doctype html><html lang="fr"><meta charset="utf-8"><title>Touch Unique — Google Drive</title>
<style>body{font:16px system-ui;background:#fff8f6;color:#1c1013;display:grid;place-items:center;min-height:100vh;margin:0}
div{background:#fff;border:1px solid #e6ccd0;border-radius:16px;padding:28px;max-width:420px;text-align:center}
b{color:%s}button{margin-top:16px;padding:10px 18px;border:0;border-radius:10px;background:%s;color:#fff;cursor:pointer}</style>
<div><b>%s</b><p>%s</p><button onclick="window.close()">Fermer</button></div>
<script>try{window.opener&&window.opener.postMessage({type:'tus-google',ok:%s},'*')}catch(e){}</script></html>""" % (
        color, color, "Connexion réussie" if ok else "Connexion impossible", message, "true" if ok else "false")
