"""Préparation des valeurs et simulation jour par jour (utilisée par le backtest ET par le suivi réel)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .features import preparer
from .portfolio import Portefeuille
from .strategy import evaluer

CHAMPS = ("open", "high", "low", "close", "atr", "seances_resultats", "score", "stop")


def preparer_tout(donnees: dict, cfg: Config, resultats: dict | None = None) -> dict:
    resultats = resultats or {}
    mkt, sec = donnees.get(cfg.marche), donnees.get(cfg.secteur)
    out = {}
    for s in cfg.valeurs:
        if s in donnees and len(donnees[s]) >= 260:
            out[s] = evaluer(preparer(donnees[s], mkt, sec), cfg, s, resultats.get(s, []))
    return out


class Rejoueur:
    """Accès rapide aux données de chaque valeur, jour par jour."""

    def __init__(self, evalues: dict):
        self.ev = evalues
        self.arr = {s: {k: d[k].to_numpy(dtype=float) for k in CHAMPS} | {"setup": d["setup"].to_numpy()}
                    for s, d in evalues.items()}
        self.pos = {s: {t: i for i, t in enumerate(d.index)} for s, d in evalues.items()}
        self.dates = sorted(set().union(*[set(d.index) for d in evalues.values()])) if evalues else []

    def barres(self, date) -> dict:
        out = {}
        for s, a in self.arr.items():
            i = self.pos[s].get(date)
            if i is not None and np.isfinite(a["close"][i]):
                out[s] = {k: a[k][i] for k in ("open", "high", "low", "close", "atr", "seances_resultats")}
        return out

    def signaux(self, date, seuil: float) -> list[dict]:
        out = []
        for s, a in self.arr.items():
            i = self.pos[s].get(date)
            if i is None or not a["setup"][i] or a["score"][i] < seuil or not np.isfinite(a["stop"][i]):
                continue
            out.append({"symbole": s, "setup": a["setup"][i], "score": float(a["score"][i]), "stop": float(a["stop"][i]),
                        "close": float(a["close"][i]), "atr": float(a["atr"][i]), "date": str(date)[:10], "i": i})
        return out


def simuler(evalues: dict, cfg: Config, debut=None, fin=None, capital: float = 100_000.0,
            seuil: float | None = None) -> tuple[Portefeuille, pd.Series, pd.Series]:
    """Renvoie (portefeuille final, valeur quotidienne, part investie quotidienne)."""
    seuil = cfg.seuil if seuil is None else seuil
    rj = Rejoueur(evalues)
    pf = Portefeuille(cfg, capital)
    dates = [d for d in rj.dates if (debut is None or d >= pd.Timestamp(debut)) and (fin is None or d <= pd.Timestamp(fin))]
    valeurs, investi = [], []
    for d in dates:
        pf.jour(str(d)[:10], rj.barres(d), rj.signaux(d, seuil))
        v = pf.valeur()
        valeurs.append(v)
        investi.append(1 - pf.cash / v if v > 0 else 0)
    idx = pd.DatetimeIndex(dates)
    return pf, pd.Series(valeurs, index=idx), pd.Series(investi, index=idx)


def performances(courbe: pd.Series) -> dict:
    if len(courbe) < 2:
        return {}
    ret = (courbe / courbe.shift(1) - 1).dropna()
    annees = (courbe.index[-1] - courbe.index[0]).days / 365.25
    cagr = (courbe.iloc[-1] / courbe.iloc[0]) ** (1 / annees) - 1 if annees > 0 else np.nan
    dd = (courbe / courbe.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan
    return {"cagr": cagr * 100, "dd_max": dd * 100, "sharpe": sharpe, "total": (courbe.iloc[-1] / courbe.iloc[0] - 1) * 100}
