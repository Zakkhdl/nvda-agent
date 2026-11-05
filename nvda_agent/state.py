"""Mémoire de l'agent entre deux passes (fichier JSON conservé par GitHub Actions)."""
from __future__ import annotations

import json
import os
import tempfile

VERSION = 2


def charger(chemin: str) -> dict:
    try:
        with open(chemin, encoding="utf-8") as fh:
            s = json.load(fh)
        if isinstance(s, dict) and s.get("version") == VERSION:
            return s
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"version": VERSION}


def sauver(chemin: str, etat: dict) -> None:
    etat["version"] = VERSION
    dossier = os.path.dirname(os.path.abspath(chemin))
    fd, tmp = tempfile.mkstemp(dir=dossier, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(etat, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, chemin)
