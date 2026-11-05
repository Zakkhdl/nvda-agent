"""Réglages de l'agent. Tout se règle par variables d'environnement (secrets et variables GitHub)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
PARIS = ZoneInfo("Europe/Paris")

LISTE_DEFAUT = "NVDA,AMD,AVGO,TSM,ASML,MU,MSFT,GOOGL,AMZN,META"
SEMIS = {"NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "QCOM", "INTC", "ARM", "AMAT", "LRCX", "KLAC",
         "MRVL", "TXN", "ADI", "NXPI", "ON", "SMCI", "MCHP", "SNPS", "CDNS"}


def _env(name: str, default, cast=str):
    raw = os.getenv(name, "")
    raw = raw.strip() if isinstance(raw, str) else raw
    if raw == "":
        return default
    try:
        return cast(raw.replace(",", ".") if cast is float else raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    valeurs: tuple = tuple(LISTE_DEFAUT.split(","))
    marche: str = "QQQ"            # référence Nasdaq 100
    secteur: str = "SMH"           # référence semi-conducteurs
    seuil: int = 60                # note mini (sur 100) pour un signal d'achat
    seuil_a: int = 75              # note mini pour la note A
    max_positions: int = 5         # positions ouvertes en même temps, au maximum
    max_entrees_jour: int = 2      # nouveaux achats par jour, au maximum
    risque_pct: float = 1.0        # % du capital perdu si le stop est touché
    poids_max_pct: float = 25.0    # % du capital au maximum dans une seule valeur
    capital_eur: float = 0.0       # optionnel : active le calcul du nombre d'actions
    frais_pct: float = 0.10        # frais par ordre (commission + écart + change amorti), en %
    stop_min_atr: float = 1.5      # distance du stop : au moins 1,5 fois la volatilité journalière
    stop_max_atr: float = 3.5      # ... et au plus 3,5 fois
    objectif_r: float = 2.0        # objectif 1 à 2 R (R = distance entrée-stop)
    suiveur_atr: float = 3.0       # stop suiveur : plus haute clôture moins 3 fois la volatilité
    duree_max: int = 40            # sortie après 40 séances (8 semaines) au plus tard
    ecart_ouverture_atr: float = 1.0  # pas d'achat si l'ouverture dépasse la clôture + 1 volatilité
    resultats_blocage: int = 5     # pas de nouvel achat à moins de 5 séances des résultats
    state_file: str = "state.json"
    events_file: str = "evenements.json"
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    telegram_token: str = ""
    telegram_chat: str = ""

    def lien(self, symbole: str) -> str:
        return f"https://www.tradingview.com/chart/?symbol={symbole}"


def load_config() -> Config:
    valeurs = tuple(v.strip().upper() for v in _env("VALEURS", LISTE_DEFAUT).split(",") if v.strip())
    return Config(
        valeurs=valeurs or tuple(LISTE_DEFAUT.split(",")),
        marche=_env("REF_MARCHE", "QQQ").upper(),
        secteur=_env("REF_SECTEUR", "SMH").upper(),
        seuil=_env("SEUIL_SCORE", 60, int),
        seuil_a=_env("SEUIL_A", 75, int),
        max_positions=_env("MAX_POSITIONS", 5, int),
        max_entrees_jour=_env("MAX_ACHATS_JOUR", 2, int),
        risque_pct=_env("RISQUE_PCT", 1.0, float),
        poids_max_pct=_env("POIDS_MAX_PCT", 25.0, float),
        capital_eur=_env("CAPITAL_EUR", 0.0, float),
        frais_pct=_env("FRAIS_PCT", 0.10, float),
        stop_min_atr=_env("STOP_MIN_ATR", 1.5, float),
        stop_max_atr=_env("STOP_MAX_ATR", 3.5, float),
        objectif_r=_env("OBJECTIF_R", 2.0, float),
        suiveur_atr=_env("SUIVEUR_ATR", 3.0, float),
        duree_max=_env("DUREE_MAX", 40, int),
        state_file=_env("STATE_FILE", "state.json"),
        events_file=_env("EVENTS_FILE", "evenements.json"),
        ntfy_topic=_env("NTFY_TOPIC", ""),
        ntfy_server=_env("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        telegram_token=_env("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat=_env("TELEGRAM_CHAT_ID", ""),
    )
