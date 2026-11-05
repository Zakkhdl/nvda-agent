"""Réglages de l'agent. Tout se règle par variables d'environnement (secrets et variables GitHub)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
PARIS = ZoneInfo("Europe/Paris")


def _env(name: str, default, cast=str):
    raw = os.getenv(name, "")
    raw = raw.strip() if isinstance(raw, str) else raw
    if raw == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    symbol: str = "NVDA"
    marche: str = "QQQ"          # référence Nasdaq 100
    secteur: str = "SMH"         # référence semi-conducteurs
    seuil: int = 65              # score mini (sur 100) pour envoyer un signal
    seuil_a: int = 80            # score mini pour la note A
    max_trades_jour: int = 4     # pas plus de signaux suivis par séance
    seuil_mouvement: float = 2.5  # % de variation en 30 min pour l'alerte "mouvement brusque"
    capital_eur: float = 0.0     # optionnel : capital pour calculer une taille de position
    risque_pct: float = 1.0      # % du capital risqué par signal (si capital renseigné)
    frais_pct: float = 0.03      # frais + écart achat/vente aller-retour, en % du prix
    stop_min_atr: float = 2.5    # distance minimale du stop en ATR 5 min
    state_file: str = "state.json"
    events_file: str = "evenements.json"
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    telegram_token: str = ""
    telegram_chat: str = ""
    twelvedata_key: str = ""

    @property
    def lien_graphique(self) -> str:
        return f"https://www.tradingview.com/chart/?symbol=NASDAQ%3A{self.symbol}"


def load_config() -> Config:
    return Config(
        symbol=_env("SYMBOL", "NVDA").upper(),
        marche=_env("REF_MARCHE", "QQQ").upper(),
        secteur=_env("REF_SECTEUR", "SMH").upper(),
        seuil=_env("SEUIL_SCORE", 65, int),
        seuil_a=_env("SEUIL_A", 80, int),
        max_trades_jour=_env("MAX_SIGNAUX_JOUR", 4, int),
        seuil_mouvement=_env("SEUIL_MOUVEMENT", 2.5, float),
        capital_eur=_env("CAPITAL_EUR", 0.0, float),
        risque_pct=_env("RISQUE_PCT", 1.0, float),
        frais_pct=_env("FRAIS_PCT", 0.03, float),
        stop_min_atr=_env("STOP_MIN_ATR", 2.5, float),
        state_file=_env("STATE_FILE", "state.json"),
        events_file=_env("EVENTS_FILE", "evenements.json"),
        ntfy_topic=_env("NTFY_TOPIC", ""),
        ntfy_server=_env("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        telegram_token=_env("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat=_env("TELEGRAM_CHAT_ID", ""),
        twelvedata_key=_env("TWELVEDATA_API_KEY", ""),
    )
