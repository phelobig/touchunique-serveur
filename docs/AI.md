# Couche IA — Touch Unique Studio

L'IA se compose de deux couches complémentaires :

1. **Couche locale déterministe** (`ai/engine.js`, copié dans `app/js/automation.js`) : elle structure, classe et prépare les tâches, les briefs et les cycles de routine. Chaque sortie reste modifiable et tracée dans l'application.
2. **Assistant Internet serveur** (`POST /api/ai`, `server/proxy.py`) : accès réel à Internet via un fournisseur public sans clé, avec repli vers Perplexity, OpenAI, Gemini et Anthropic si des clés sont configurées. Il est **gratuit et illimité pour tous**, sans quota ni « essais » : seule une limite technique très large (au moins 120 requêtes/min/IP) protège contre les abus.

Le serveur peut effectuer une recherche factuelle (`web_context`) sur l'API Wikipédia de la langue détectée (`fr.wikipedia.org` ou `en.wikipedia.org`) et renvoyer jusqu'à trois sources avec URL réelle. Les réponses ne prétendent jamais qu'une publication ou un paiement a été effectué sans confirmation réelle de l'API concernée.

## API locale

| Fonction | Sortie |
|---|---|
| `brief(input)` | Brief structuré : thème, objectif, audience, ton, angle, promesse, structure, checklist. |
| `tasksForProject(project)` | Tâches ordonnées par phase (Brief → Conception → Production → Livraison), avec variantes vidéo / formation. |
| `content(input)` | Pack éditorial : titres, légendes, scripts, hashtags, calendrier 5 jours, score. |
| `scoreLead(lead)` | `{ score, level ('chaud'|'tiède'|'froid'), action }`. |
| `offerCopy(product)` | Titre, puces, CTA et note de prix pour une offre. |
| `shopActions(products, leads)` | Suggestions : mise en avant, vérification de capacité, observation. |
| `socialLinks(text)` | Liens de composition (WhatsApp, Facebook, Instagram, LinkedIn, X). |
| `runCycle(state)` | Cycle complet : leads scorés → projets, tâches, publications préparées, suggestions boutique, journal. |

Le contrat de l'assistant reste `{ answer, sources, at }` : toute réponse affiche ses sources dans le panneau latéral.

## Assistant serveur /api/ai

Requête : `{ "prompt": "...", "system": "...", "lang": "fr"|"en", "provider": "auto", "maxTokens": 900 }`.

Réponse : `{ "ok": true, "text": "...", "provider": "...", "model": "...", "sources": [...], "lang": "fr"|"en" }`.

- La langue est fournie par le client (`lang`) ou détectée depuis le prompt et la consigne ; par défaut le français. La base `server/language.py` est le miroir côté serveur de `shared/tus-language.js` : plus de 25 intentions traduites, consigne système complète et réponses honnêtes en FR/EN.
- L'ordre de repli est : `web` (public, sans clé) → `perplexity` → `openai` → `gemini` → `anthropic`. Une réponse locale honnête est renvoyée si aucun fournisseur n'est joignable.
- `/api/status` indique les langues `['fr','en']`, la version 7 et des indicateurs booléens des fournisseurs. Aucune clé ni valeur de secret n'est exposée.

## Secrets et confidentialité

Les clés IA, tokens des réseaux sociaux et identifiants Google Drive sont chargés côté serveur depuis les variables d'environnement ou un fichier privé local (`server/envloader.py` : `TUS_PRIVATE_ENV`, puis `%APPDATA%\touch-unique-studio\private-env.txt`, puis `server/private-env.txt`). Les valeurs ne sont jamais affichées, journalisées ou renvoyées au navigateur ; seuls des noms et des indicateurs booléens sont visibles. Voir `server/.env.example` pour la liste des noms (sans valeurs).

## Garanties

- Aucune publication n'est annoncée sans identifiant réel renvoyé par le réseau social ; la préparation d'un contenu ne vaut pas publication.
- Aucun paiement, remboursement ni certification n'est simulé dans le chat.
- Les faits non vérifiables sont signalés comme tels ; l'assistant dit clairement quand il ne sait pas.
- Contact officiel : WhatsApp https://wa.me/22655041530 (Burkina-Faso).
