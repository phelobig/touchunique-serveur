# Serveur Touch Unique Studio

Proxy déployé sur Render : IA Internet gratuite et illimitée, réseaux sociaux, Google Drive, OAuth, fichiers et messagerie site ↔ application. Les secrets restent côté serveur : variables d'environnement, fichier privé local chargé par `envloader.py` ou coffre chiffré `vault.json` (`TUS_VAULT_KEY`). Aucune clé n'est envoyée au navigateur ni journalisée.

**URL publique :** `https://touchunique-serveur.onrender.com`  
Le site `https://phelobig.github.io/touchunique-site/?v=18` est préconnecté à cette URL : l'envoi d'un message ne demande aucun jeton au visiteur. L'application administrateur utilise la même URL avec la clé `X-Tus-Key` saisie dans ses réglages.

## Démarrage

```bash
python proxy.py
# PORT=10000 HOST=0.0.0.0 pour Render
```

Au démarrage, `envloader.load()` complète silencieusement `os.environ` depuis, dans cet ordre :

1. le chemin indiqué par `TUS_PRIVATE_ENV` ;
2. `%APPDATA%\touch-unique-studio\private-env.txt` (par défaut `C:\Users\NITRO\AppData\Roaming\touch-unique-studio\private-env.txt`) ;
3. `server/private-env.txt` (non versionné).

Format : `CLE=valeur`, un par ligne ; commentaires et lignes vides ignorés. Une variable déjà définie n'est jamais écrasée. Aucune valeur n'est affichée, journalisée ou renvoyée : `envloader.available_keys()` ne donne que des noms. Voir `.env.example` pour la liste complète des noms (sans valeurs réelles).

Variables principales :

- `TUS_VAULT_KEY` : clé du coffre chiffré (générée automatiquement par Render).
- `TUS_PROXY_TOKEN` : clé partagée `X-Tus-Key` pour les appels administrateur. Les visiteurs du site n'en ont pas besoin.
- `ALLOWED_ORIGINS` : origines autorisées, séparées par des virgules.
- `TUS_DEFAULT_LANG` : `fr` (défaut) ou `en`, utilisé quand rien n'est détecté.
- `AI_RATE_LIMIT_PER_MIN` : limite technique IA, au moins 120 requêtes/min/IP (aucun quota, aucun essai).
- `GOOGLE_REDIRECT_URI` : callback Google (`https://touchunique-serveur.onrender.com/api/google/callback`).
- `PUBLIC_BASE_URL` : base HTTPS publique utilisée pour tous les callbacks OAuth.

## Assistant IA et langues

- `POST /api/ai` accepte `{ prompt, system?, lang?, provider?, maxTokens? }` et renvoie `{ ok, text, provider, model, sources, lang }`.
- Langues prises en charge : `fr` et `en`. La langue est fournie par le client ou détectée depuis le prompt ; la consigne système complète vient de `language.py` (miroir de `shared/tus-language.js`).
- Fournisseur public sans clé en priorité (`web`), puis repli `perplexity` → `openai` → `gemini` → `anthropic`. Gratuit et illimité pour tous ; aucune notion d'essai ni de quota.
- La recherche factuelle utilise l'API Wikipédia de la langue détectée avec un User-Agent explicite et renvoie jusqu'à trois sources avec URL réelle.
- `GET /api/status` expose `ai.web: true`, des indicateurs booléens des fournisseurs, `langues: ['fr','en']` et `version: 7` — jamais de secret.
- Aucune publication ni paiement n'est simulé : un statut « publié » exige l'identifiant réel renvoyé par le réseau.

## Messagerie site ↔ application

Routes publiques :

- `GET /api/messages/config` : état des notifications push et clé publique VAPID.
- `GET /api/messages?thread=<id>&token=<même id>` : conversations d'un visiteur (le jeton prouve qu'il possède l'identifiant généré localement).
- `POST /api/messages` : message visiteur (`thread`, `token`, `name`, `phone`, `email`, `text`, `kind`) ou pièce jointe base64.
- `POST /api/messages/subscribe` : abonnement Web Push du visiteur ou de l'administrateur.
- `GET /api/messages/file/<nom>` : pièce jointe.

Routes administrateur (`X-Tus-Key`) :

- `GET /api/messages?admin=1&since=<horodatage>` : toutes les conversations, utilisé par l'application, Android et Windows.
- `POST /api/messages` avec `admin: true` : réponse de l'administrateur.

Stockage : `server/data/messages.json` et `server/data/messages/`. Limite 8 Mo par pièce jointe et 40 messages par conversation sur 10 minutes. Aucun accusé de réception n'est affiché côté site sans réponse positive du serveur.

## Compteur de visiteurs

- `GET /api/visits` : totaux publics (`total`, `today`, `views`, `online`) — aucun jeton requis.
- `POST /api/visits` : signal envoyé par le site à chaque visite, sans jeton ni donnée personnelle.
- Les totaux sont persistés dans `data/visits.json` côté serveur. Sur l'offre Render gratuite le système de fichiers est temporaire : les compteurs survivent aux redémarrages mais sont réinitialisés lors d'un redéploiement.

## Sécurité

- Le site public ne connaît que l'URL du serveur et son identifiant de conversation local.
- Tokens sociaux, clés IA et secrets OAuth sont chargés côté serveur ; seuls des indicateurs booléens sont exposés.
- Aucune route (y compris `/api/status`) ne renvoie de secret ni de valeur de configuration sensible.
- Les messages d'erreur amont sont réduits à leur nature : corps de réponse et URL contenant une clé ne sont jamais journalisés.
- CORS restreint aux origines déclarées dans `ALLOWED_ORIGINS`.
