"""Envoi des alertes : ntfy (iPhone et Android) et/ou Telegram."""
from __future__ import annotations

import requests

from .config import Config
from .util import log

EMOJI = {"green_circle": "🟢", "red_circle": "🔴", "zap": "⚡", "sunrise": "🌅", "warning": "⚠️",
         "white_check_mark": "✅", "dart": "🎯", "trophy": "🏆", "x": "❌", "handshake": "🤝",
         "bell": "🔔", "arrows_counterclockwise": "🔄", "bar_chart": "📊"}


def canal_configure(cfg: Config) -> bool:
    return bool(cfg.ntfy_topic or (cfg.telegram_token and cfg.telegram_chat))


def envoyer(cfg: Config, titre: str, corps: str, tag: str = "", priorite: int = 3, dry_run: bool = False) -> bool:
    log(f"ALERTE : {titre}\n{corps}")
    if dry_run:
        return True
    ok = False
    if cfg.ntfy_topic:
        try:
            r = requests.post(cfg.ntfy_server, json={
                "topic": cfg.ntfy_topic, "title": titre, "message": corps, "priority": priorite,
                "tags": [tag] if tag else [], "click": cfg.lien_graphique,
            }, timeout=15)
            r.raise_for_status()
            ok = True
        except Exception as e:
            log(f"Échec ntfy : {e}")
    if cfg.telegram_token and cfg.telegram_chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage", json={
                "chat_id": cfg.telegram_chat, "text": f"{EMOJI.get(tag, '')} {titre}".strip() + "\n\n" + corps,
                "disable_web_page_preview": True,
            }, timeout=15)
            r.raise_for_status()
            ok = True
        except Exception as e:
            log(f"Échec Telegram : {e}")
    if not canal_configure(cfg):
        log("Aucun canal configuré : alerte affichée ici seulement.")
    return ok
