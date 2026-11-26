# Serveur Touch Unique Studio

Proxy gratuit déployé sur Render : IA, réseaux sociaux, Google Drive, OAuth, fichiers et messagerie site ↔ application. Les secrets restent sur le serveur dans `vault.json` chiffré (`TUS_VAULT_KEY`) ou dans les variables d’environnement. Aucune clé n’est envoyée au navigateur.

## Démarrage

```bash
python proxy.py
# PORT=10000 HOST=0.0.0.0 pour Render
```

Variables :

- `TUS_VAULT_KEY` : clé du coffre chiffré (générée automatiquement par Render).
- `TUS_PROXY_TOKEN` : clé partagée `X-Tus-Key` pour les appels administrateur (IA, fichiers, réponses messagerie, publication). Les visiteurs du site n’en ont pas besoin.
- `ALLOWED_ORIGINS` : origines autorisées, séparées par des virgules.
- `TUS_GOOGLE_REDIRECT_URI`, `TUS_OAUTH_REDIRECT_URI` : callbacks HTTPS à déclarer chez les fournisseurs.

## Messagerie site ↔ application

Routes publiques :

- `GET /api/messages/config` : état des notifications push et clé publique VAPID.
- `GET /api/messages?thread=<id>&token=<même id>` : conversations d’un visiteur (le jeton prouve qu’il possède l’identifiant généré localement).
- `POST /api/messages` : message visiteur (`thread`, `token`, `name`, `phone`, `email`, `text`, `kind`) ou pièce jointe base64.
- `POST /api/messages/subscribe` : abonnement Web Push du visiteur ou de l’administrateur.
- `GET /api/messages/file/<nom>` : pièce jointe.

Routes administrateur (`X-Tus-Key`) :

- `GET /api/messages?admin=1&since=<horodatage>` : toutes les conversations, utilisé par l’application, Android et Windows.
- `POST /api/messages` avec `admin: true` : réponse de l’administrateur.

Stockage : `server/data/messages.json` et `server/data/messages/`. Limite 8 Mo par pièce jointe et 40 messages par conversation sur 10 minutes. Aucun accusé de réception n’est affiché côté site sans réponse positive du serveur.

Notifications Web Push : `pywebpush` (voir `requirements.txt`). Les clés VAPID sont générées une seule fois dans le coffre via `python -c "import messages; messages.ensure_keys()"`. Android utilise un `AlarmManager` toutes les 5 minutes avec notification native, même hors application. Windows notifie via Electron lorsque l’application est ouverte.

## Sécurité

- Le site public ne connaît que l’URL du serveur et son identifiant de conversation local.
- Les tokens sociaux, clés IA et secrets OAuth ne sont jamais exposés au navigateur.
- Les publications réelles ne sont effectuées que sur demande explicite et uniquement si le fournisseur renvoie un identifiant de publication ; sinon le statut reste « à valider ».
- CORS restreint aux origines déclarées dans `ALLOWED_ORIGINS`.
