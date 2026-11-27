# -*- coding: utf-8 -*-
"""Chargement silencieux des secrets locaux dans os.environ.

Ordre de recherche (première valeur trouvée gagne ; les variables déjà
définies ne sont jamais écrasées) :

1. chemin explicite dans ``TUS_PRIVATE_ENV`` ;
2. ``%APPDATA%\\touch-unique-studio\\private-env.txt``
   (par défaut ``C:\\Users\\NITRO\\AppData\\Roaming\\touch-unique-studio\\private-env.txt``) ;
3. ``server/private-env.txt`` (non versionné).

Format : une affectation ``CLE=valeur`` par ligne. Les commentaires
(``#``), les lignes vides et les espaces superflus sont ignorés ; les guillemets
simples ou doubles entourant une valeur sont retirés. Aucune valeur n'est
jamais journalisée, renvoyée ou sérialisée : ``available_keys()`` ne donne
que les noms des clés présentes dans les fichiers.

Bibliothèque standard Python uniquement.
"""

import os
import re
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_APPDATA = os.environ.get("APPDATA", "") or str(
    Path.home() / "AppData" / "Roaming"
)
ROAMING_FILE = Path(_APPDATA) / "touch-unique-studio" / "private-env.txt"
LOCAL_FILE = Path(__file__).resolve().parent / "private-env.txt"

_SEEN = set()
_LOADED = False


def _candidates():
    """Chemins candidates, dans l'ordre de priorité, sans jamais les journaliser."""
    paths = []
    explicit = str(os.environ.get("TUS_PRIVATE_ENV", "") or "").strip().strip('"\'')
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(ROAMING_FILE)
    paths.append(LOCAL_FILE)
    return paths


def _parse_line(line):
    """Retourne (nom, valeur) ou None pour une ligne vide / commentaire."""
    raw = str(line or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.lower().startswith("export "):
        raw = raw[7:].lstrip()
    key, sep, value = raw.partition("=")
    key = key.strip()
    if not sep or not _KEY.match(key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not value:
        return None
    return key, value


def load():
    """Complète ``os.environ`` depuis les fichiers privés, sans écraser ni journaliser.

    Retourne la liste triée des noms de variables réellement ajoutées (jamais
    les valeurs). L'appel est idempotent : les fichiers sont relus à chaque
    appel mais une variable déjà définie reste intacte.
    """
    global _LOADED
    added = set()
    for path in _candidates():
        try:
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, ValueError, UnicodeError):
            # Un fichier illisible est ignoré silencieusement : aucun secret,
            # aucun chemin et aucune valeur dans les logs.
            continue
        for line in content.splitlines():
            try:
                parsed = _parse_line(line)
            except Exception:
                continue
            if not parsed:
                continue
            key, value = parsed
            _SEEN.add(key)
            if key in os.environ:
                continue
            os.environ[key] = value
            added.add(key)
    _LOADED = True
    return sorted(added)


def available_keys():
    """Noms des clés vues dans les fichiers privés (jamais de valeurs)."""
    if not _LOADED:
        load()
    return sorted(_SEEN)
