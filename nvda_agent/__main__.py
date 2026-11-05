"""Point d'entrée.

  python -m nvda_agent              une passe (GitHub Actions ou tâche planifiée)
  python -m nvda_agent --loop       en continu sur ton ordinateur, toutes les 5 minutes
  python -m nvda_agent --test       notification de test
  python -m nvda_agent --backtest   mesure des signaux sur les ~60 dernières séances
  python -m nvda_agent --force      analyse immédiate même marché fermé
  python -m nvda_agent --dry-run    affiche les alertes sans les envoyer
"""
from __future__ import annotations

import argparse
import sys
import time

from .agent import executer
from .config import load_config
from .notify import canal_configure, envoyer
from .util import log


def main() -> None:
    ap = argparse.ArgumentParser(prog="nvda_agent", description="Agent de signaux techniques NVIDIA")
    ap.add_argument("--loop", action="store_true")
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
        if not envoyer(cfg, f"Test agent {cfg.symbol}", "Si tu lis ce message, les alertes fonctionnent.",
                       "white_check_mark", 3):
            sys.exit(1)
        return
    if a.backtest:
        from .backtest import lancer
        lancer(cfg)
        return
    if a.loop:
        log(f"Agent {cfg.symbol} lancé, une passe toutes les 5 minutes. Ctrl+C pour arrêter.")
        while True:
            try:
                executer(cfg, force=a.force, dry_run=a.dry_run)
            except Exception as e:  # la boucle ne doit jamais s'arrêter
                log(f"Erreur inattendue : {e}")
            time.sleep(300 - (time.time() % 300) + 20)
    executer(cfg, force=a.force, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
