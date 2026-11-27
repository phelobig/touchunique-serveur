# Déploiement — Touch Unique Studio

Deux dépôts statiques, sans build et sans dépendance. L’application de gestion est distribuée uniquement en natif (Android et Windows) : aucun lien public ne mène vers elle.

| Dépôt | Contenu à publier | URL |
|---|---|---|
| `phelobig.github.io` | `deploy/root/*` | `https://phelobig.github.io/` |
| `touchunique-site` | `deploy/site/*` | `https://phelobig.github.io/touchunique-site/` |

Le dépôt racine ne contient qu’un accueil de redirection et un `robots.txt` valide pour l’origine `github.io`. Le paquet `deploy/app/` sert uniquement aux builds Android et Windows et au canal de mise à jour séparé `touchunique-updates`.

## Préparer les fichiers à téléverser

`git` et `gh` ne sont pas disponibles sur cette machine. Le téléversement web de GitHub (`/upload`) **aplatit l’arborescence** : les fichiers sélectionnés dans `css/`, `js/` et `assets/` arrivent tous à la racine du dépôt. Les sources conservent leurs dossiers, mais les paquets publiés utilisent des liens plats.

Générer les paquets prêts à publier :

```powershell
python deploy/prepare.py
```

Le script produit :

- `deploy/site/` — liens réécrits à la racine, cache `?v=25`, catalogue affiché par groupes de trois offres ;
- `deploy/app/` — paquet natif (Android + Windows), cache `?v=27`, non publié sur le web ;
- `deploy/root/` — `index.html`, `robots.txt`, `.nojekyll` ;
- `deploy/updates/` — manifeste `manifest.json` et ZIP signés par empreinte SHA-256, générés par `python deploy/build_update.py <version>`.

Ne pas éditer ces paquets à la main : ils sont régénérés depuis `site/` et `app/`.

## Procédure de publication

1. Créer les deux dépôts vides sur GitHub avec les noms ci-dessus.
2. Dans chaque dépôt, ouvrir **Upload files**, sélectionner tout le contenu du dossier `deploy/<nom>/*` (8 fichiers maximum par lot), puis **Commit changes**.
3. Activer **Settings → Pages → Deploy from a branch → `main` / `/ (root)`**.
4. Vérifier la présence de `.nojekyll` à la racine de chaque dépôt.
5. Forcer un rechargement (`Ctrl+F5`) après chaque mise à jour de JS/CSS. Incrémenter le `?v=` dans `deploy/prepare.py` si le cache persiste.
6. Le dépôt séparé `touchunique-updates` reçoit `deploy/updates/*` : c’est le seul canal des mises à jour en ligne, sans lien depuis le site.

## Déploiement effectué

Le 25 novembre 2026, sur le compte `phelobig` :

- `https://phelobig.github.io/` → redirection vers le site public ;
- `https://phelobig.github.io/touchunique-site/` → catalogue par groupes de trois offres, réalisations, expertises, modules IA, FAQ, devis WhatsApp.

L’application native n’est pas hébergée sur le web : installateur Windows et APK Android fournis sur demande au `+226 55 04 15 30`. Les mises à jour du paquet web intégré passent par le dépôt `touchunique-updates`.

Palette actuelle : rouge sur fond clair (blanc ivoire), texte encre, contraste vérifié. Vérifications en ligne : Lighthouse **100 / 100 / 100** (accessibilité, bonnes pratiques, SEO), console sans erreur.

## Synchronisation site ↔ application

Le site public ne contient plus l'application : la synchronisation « même origine » n'est plus utilisée. Les échanges et l'assistant Internet passent par le serveur sécurisé (`server/proxy.py`) :

1. Le site envoie `POST /api/leads` avec `{ id, ref, at, source, type, client, items, total, details, message }`.
2. L’id `ref` sert de clé d’idempotence côté serveur.
3. L’application lit l’API, avec `tus_site_leads_v1` comme simple outbox hors ligne.
4. Le catalogue partagé `tus_catalog_v1` peut être synchronisé via `/api/catalog` ; le site affiche les mêmes offres si le serveur est configuré.
5. Ne jamais simuler un paiement ni une publication : les connecteurs non configurés restent affichés « Non connecté » dans les réglages ; un statut « publié » exige un identifiant renvoyé par le réseau.
6. L'assistant `POST /api/ai` est gratuit et illimité (fournisseur Web public sans clé en priorité), avec une simple limite technique de 120 requêtes/min/IP. Il répond en français ou en anglais (`lang`), détecté ou fourni par le client.

## Cache et mises à jour

- `catalogue.json` est chargé avec `cache: 'no-store'` ; `js/data.js` sert de repli.
- Les images et la vidéo sont locales, sans CDN.
- `hero-loop.mp4` fait ~316 Ko et `hero-poster.jpg` ~60 Ko : suffisant pour un démarrage rapide.
- Incrémenter `?v=` dans `deploy/prepare.py` après modification d’un fichier texte.
- Pour l’application installée : `python deploy/build_update.py <version>` publie un ZIP vérifié par SHA-256 dans `deploy/updates/` ; Android et Windows le téléchargent et l’installent sans réinstallation.

## Serveur : secrets, langues et IA

- Déployer `server/render.yaml` (plan `free`, `startCommand: python server/proxy.py`). Le fournisseur Web public fonctionne sans aucune clé : l'IA Internet est gratuite et illimitée, sans quota ni essai. Les clés IA et tokens ne sont que des replis optionnels.
- `/api/status` (version 7) expose `ai.web: true`, des indicateurs booléens des fournisseurs, `langues: ['fr','en']`. Aucune valeur de secret n'est renvoyée ni journalisée.
- Les secrets sont lus au démarrage par `server/envloader.py`, sans affichage de valeurs : chemin `TUS_PRIVATE_ENV`, puis `%APPDATA%\touch-unique-studio\private-env.txt`, puis `server/private-env.txt` (non versionné). Une variable déjà définie dans l'environnement n'est jamais écrasée.
- `server/.env.example` liste tous les noms de variables (IA, réseaux sociaux, Google Drive, langues) sans aucune valeur réelle. Le coffre chiffré `vault.json` reste une alternative locale.
- L'analyse multimédia (`/api/media/analyze`) utilise une consigne bilingue stricte : seuls les faits réellement visibles ou audibles sont extraits, sous forme de JSON valide.

## Connecteurs optionnels

L’application affiche « Non connecté » tant que les identifiants OAuth ne sont pas fournis. Pour activer :

- obtenir les Client ID/Secret officiels (Google, Facebook, Instagram, LinkedIn, X) ;
- les saisir dans **Réglages → Connexions automatiques** : ils sont chiffrés côté serveur, jamais dans `localStorage` ;
- déclarer les URI `https://<serveur>.onrender.com/api/oauth/callback` et `https://<serveur>.onrender.com/api/google/callback` ;
- demander confirmation avant chaque publication : un statut « publié » exige un identifiant renvoyé par l’API du réseau.

Voir `server/README.md` pour la configuration du serveur.
