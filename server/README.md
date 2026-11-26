# Serveur proxy Touch Unique Studio

Il conserve les clés API, les tokens sociaux et les jetons Google **côté serveur**, dans un coffre chiffré. Le site et l’application ne voient jamais les secrets : ils reçoivent seulement l’état « connecté / non connecté ».

## Pourquoi un serveur ?

GitHub Pages ne peut exécuter que du HTML/CSS/JS statique. Pour appeler ChatGPT, Perplexity, Gemini, Claude, publier sur les réseaux et synchroniser Google Drive avec vos accès, il faut un petit serveur HTTPS.

## Déploiement gratuit sur Render

1. Créez un dépôt (par exemple `phelobig/touchunique-serveur`) contenant le dossier `server/`.
2. Sur https://render.com → **New** → **Web Service** → connectez ce dépôt.
3. Runtime : **Python 3**, build command : `pip install -r requirements.txt`, start command : `python server/proxy.py`.
4. Ajoutez toutes les variables de `server/.env.example`. **`TUS_VAULT_KEY` doit être une longue chaîne aléatoire** : c’est la clé du coffre.
5. Copiez l’URL publique (`https://xxx.onrender.com`) dans les réglages de l’application (champ « URL du serveur sécurisé ») et dans `GOOGLE_REDIRECT_URI`.
6. Dans Google Cloud Console → API Drive activée → écran de consentement → identifiants OAuth « Application Web » → ajoutez `https://xxx.onrender.com/api/google/callback` comme URI de redirection autorisée. Saisissez le Client ID et le Secret dans l’application (ils restent sur le serveur).
7. Ouvrez l’application : **Réglages → Connexions** → connectez chaque compte.

Le fichier `render.yaml` fourni pré-remplit la configuration. Le plan gratuit met le service en veille après un moment d’inactivité : le premier appel peut prendre quelques secondes.

## Démarrage local

```powershell
$env:TUS_PROXY_TOKEN="cle-de-test"
$env:TUS_VAULT_KEY="cle-maitre-de-test"
python server/proxy.py
```

Test : `Invoke-RestMethod http://localhost:8000/api/status`.

## Sécurité

- `ALLOWED_ORIGINS` limite les domaines autorisés ; l’application Windows (`app://-` / `file://`) est autorisée.
- `TUS_PROXY_TOKEN` est envoyé dans l’en-tête `X-Tus-Key` par l’application.
- Les secrets sont chiffrés dans `server/vault.json` avec la clé `TUS_VAULT_KEY` (dérivation PBKDF2-SHA256 + HMAC).
- Aucune valeur de clé n’est renvoyée au navigateur, même aux administrateurs : seulement `true/false`.
- Aucun paiement ni publication n’est simulé : un statut « publié » exige un identifiant renvoyé par l’API du réseau.

## Endpoints principaux

| Méthode | Chemin | Rôle |
| --- | --- | --- |
| GET | `/api/status` | État des IA, réseaux, Google et robots |
| POST | `/api/credentials` | Enregistre une clé/token (`{"name":"openai","value":"..."}`) |
| POST | `/api/ai` | Génère du texte (OpenAI, Perplexity, Gemini, Claude) |
| POST | `/api/publish` | Publie réellement sur le réseau demandé |
| GET/POST | `/api/robots`, `/api/robots/config`, `/api/robots/run` | Robots et planning quotidien |
| GET/POST | `/api/agents` | Configuration des quatre agents collaborateurs |
| POST | `/api/pipeline/run` | Exécute la chaîne prospection → conception → contact → rapports |
| GET/POST | `/api/files`, `/api/files/upload`, `/api/files/delete` | Dossiers entreprises/projets |
| GET | `/api/google/auth-url`, `/api/google/callback`, `/api/google/backups` | OAuth Google Drive |
| POST | `/api/google/sync`, `/api/google/restore` | Sauvegarde et restauration Drive |

## Robots quotidiens

Quatre robots sont fournis : veille techno, publication automatique, nouvelle conception et prospection. Chacun possède sa propre configuration (activé, heure, fournisseur, consigne) modifiable dans l’application ; `TUS_ROBOT_AUTORUN=1` exécute ceux qui sont dus. Les résultats sont dans `server/output/<type>/<date>.md`, l’état dans `robot_state.json`, la configuration dans `robot_config.json`.

## Pipeline collaboratif

Les quatre agents travaillent sur le même dossier entreprise/projet :

1. **Prospection** (Perplexity) cherche et cite ses sources.
2. **Conception** (Gemini) produit le brief, la maquette décrite et le devis.
3. **Contact** (Claude) prépare le message client, le planning et les tâches.
4. **Rapports** (ChatGPT) contrôle, rédige les rapports d’inspection et les publications.

Le résultat de chaque étape est enregistré dans le dossier `IA-<agent>` de l’entreprise. Une publication n’est envoyée que si l’agent émet un bloc `[[PUBLICATION:réseau]]` **et** si l’utilisateur a explicitement demandé la publication.
