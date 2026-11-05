"""Point d'entrée.

  python -m nvda_agent              passage du soir (GitHub Actions)
  python -m nvda_agent --test       notification de test
  python -m nvda_agent --backtest   backtest du portefeuille sur 20 ans
  python -m nvda_agent --force      analyse immédiate, même si la séance a déjà été traitée
  python -m nvda_agent --dry-run    affiche les alertes sans les envoyer
"""
from __future__ import annotations

import argparse
import sys

from .agent import executer
from .config import load_config
from .notify import canal_configure, envoyer
from .util import log


def main() -> None:
    ap = argparse.ArgumentParser(prog="nvda_agent", description="Agent de signaux swing (achats seulement)")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    if a.test:
        if not canal_configure(cfg):
            log("Aucun canal configuré. Renseigne NTFY_TOPIC (ou TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).")
            sys.exit(1)
        ok = envoyer(cfg, "Test agent swing", f"Les alertes fonctionnent. Valeurs suivies : {', '.join(cfg.valeurs)}.",
                     "white_check_mark", 3)
        sys.exit(0 if ok else 1)
    if a.backtest:
        from .backtest import lancer
        lancer(cfg)
        return
    executer(cfg, force=a.force, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
