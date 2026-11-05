"""Stratégie swing (quelques semaines), achats seulement.

3 configurations d'achat, évaluées chaque soir à la clôture :
- REPLI   : repli sur la MM20 ou RSI détendu dans une tendance haussière, puis reprise.
- CASSURE : première clôture au plus haut de 50 séances, avec volume.
- REPRISE : retour au-dessus de la MM50 après une correction, dans une tendance de fond intacte.

Chaque signal reçoit une note sur 100 : 50 points de départ, ajustés par 11 facteurs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SEMIS, Config

SETUPS = {
    "REPLI": "Repli dans une tendance haussière",
    "CASSURE": "Cassure d'un plus haut de 50 séances",
    "REPRISE": "Reprise de la moyenne 50 jours",
}


# Ajustement selon l'historique 2006-2026 de chaque configuration, mesuré sur la liste suivie ET sur
# 15 autres valeurs : la cassure a une espérance proche de zéro, contre +0,15 à +0,25 R pour le repli.
PRIOR = {"REPLI": 0, "CASSURE": -8, "REPRISE": 0}


def seances_avant_resultats(index: pd.DatetimeIndex, dates: list[str]) -> np.ndarray:
    """Nombre de séances entre chaque jour et la prochaine publication de résultats (inf si inconnue)."""
    out = np.full(len(index), np.inf)
    if not dates:
        return out
    ds = np.array(sorted({np.datetime64(x, "D") for x in dates}))
    jours = index.values.astype("datetime64[D]")
    pos = np.searchsorted(ds, jours, side="right")  # prochaine date strictement après le jour
    m = pos < len(ds)
    out[m] = np.busday_count(jours[m], ds[pos[m]])
    return out


def evaluer(d: pd.DataFrame, cfg: Config, symbole: str, resultats: list[str] | None = None) -> pd.DataFrame:
    """Ajoute à d : setup, score, stop, et les points de chaque facteur (colonnes f_*)."""
    c, o, h = d["close"], d["open"], d["high"]
    atr = d["atr"]
    tendance = (c > d["sma200"]) & (d["sma50"] > d["sma200"]) & (d["pente200"] > 0)

    setups = {}
    # 1. Repli dans une tendance haussière
    repli = (d["bas5"] <= d["sma20"] * 1.01) | (d["rsi_min5"] <= 45)
    declencheur = (c > h.shift(1)) & (c > o) & (d["rsi"] > d["rsi"].shift(1))
    cond = tendance & repli & (c >= d["sma50"] * 0.97) & declencheur & (d["dist_haut52"] >= -0.25)
    setups["REPLI"] = (cond, d["bas5"] - 0.5 * atr)
    # 2. Cassure d'un plus haut de 50 séances
    cond = ((c > d["haut50c"]) & (c.shift(1) <= d["haut50c"].shift(1)) & (d["vol_rel"] >= 1.4)
            & (c > d["sma200"]) & (d["sma50"] > d["sma200"]))
    setups["CASSURE"] = (cond, d["bas10"] - 0.3 * atr)
    # 3. Reprise de la MM50 après une correction
    cond = ((d["sous50_10j"] >= 5) & (c > d["sma50"]) & (c.shift(1) <= d["sma50"].shift(1))
            & (c > d["sma200"]) & (d["pente200"] > 0) & (d["vol_rel"] >= 1.1))
    setups["REPRISE"] = (cond, d["bas10"] - 0.3 * atr)

    # Facteurs communs
    F = {}
    F["marche"] = np.select([d["regime_marche"] > 0, d["regime_marche"] < 0], [10, -20], 0)
    semi = symbole in SEMIS
    F["secteur"] = np.select([d["regime_secteur"] > 0, d["regime_secteur"] < 0], [5, -5], 0) if semi else np.zeros(len(d))
    F["force_relative"] = np.select([d["rs126"] > 10, d["rs126"] > 0, d["rs126"] < -10], [8, 4, -8], 0)
    F["tendance_longue"] = np.select([(c > d["sma150"]) & (d["pente150"] > 0), c < d["sma150"]], [5, -8], 0)
    F["adx"] = np.where(d["adx"] >= 25, 4, 0)
    F["sommet"] = np.select([d["dist_haut52"] >= -0.10, d["dist_haut52"] <= -0.30], [5, -8], 0)
    F["volume"] = np.select([d["vol_rel"] >= 1.5, d["vol_rel"] < 0.8], [5, -4], 0)
    F["extension"] = np.where(c > d["sma50"] * 1.20, -8, 0)
    F["rsi"] = np.where(d["rsi"] > 75, -6, 0)
    nb = seances_avant_resultats(d.index, resultats or [])
    d["seances_resultats"] = nb
    F["resultats"] = np.select([nb <= cfg.resultats_blocage, nb <= 10], [-30, -8], 0)
    base_commune = 50 + sum(np.asarray(x, dtype=float) for x in F.values())

    meilleur_score = np.full(len(d), -1.0)
    setup = np.array([""] * len(d), dtype=object)
    stop = np.full(len(d), np.nan)
    f_base = np.zeros(len(d))
    f_risque = np.zeros(len(d))
    for nom, (cond, stop_struct) in setups.items():
        s = np.fmin(stop_struct, c - cfg.stop_min_atr * atr)
        s = np.fmax(s, c - cfg.stop_max_atr * atr)
        risque_pct = (c - s) / c
        pts_risque = np.where(risque_pct > 0.12, -8, 0)
        pts_base = np.select([d["base30"] <= 0.15, d["base30"] > 0.35], [5, -5], 0) if nom == "CASSURE" else np.zeros(len(d))
        pts_base = pts_base + PRIOR.get(nom, 0)
        sc = np.clip(base_commune + pts_risque + pts_base, 0, 100)
        valide = cond.fillna(False).to_numpy() & np.isfinite(s) & (s < c) & np.isfinite(sc)
        mieux = valide & (sc > meilleur_score)
        meilleur_score = np.where(mieux, sc, meilleur_score)
        setup = np.where(mieux, nom, setup)
        stop = np.where(mieux, s, stop)
        f_base = np.where(mieux, pts_base, f_base)
        f_risque = np.where(mieux, pts_risque, f_risque)

    out = d.copy()
    out["setup"] = setup
    out["score"] = meilleur_score
    out["stop"] = stop
    for k, v in F.items():
        out[f"f_{k}"] = v
    out["f_base"] = f_base
    out["f_risque"] = f_risque
    return out
