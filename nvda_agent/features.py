"""Variables journalières utilisées par la stratégie, valeur par valeur.

Toutes les variables du jour J n'utilisent que les données connues à la clôture de J.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


def regime(df: pd.DataFrame | None, index: pd.DatetimeIndex) -> pd.Series:
    """+1 : tendance haussière (au-dessus de la MM200 et MM50 > MM200). -1 : sous la MM200. 0 : entre les deux."""
    if df is None or df.empty:
        return pd.Series(np.nan, index=index)
    c = df["close"]
    m50, m200 = ind.sma(c, 50), ind.sma(c, 200)
    reg = np.where((c > m200) & (m50 > m200), 1, np.where(c < m200, -1, 0))
    reg = pd.Series(reg, index=df.index, dtype=float).where(m200.notna())
    return reg.reindex(index).ffill(limit=3)


def preparer(df: pd.DataFrame, marche: pd.DataFrame | None, secteur: pd.DataFrame | None) -> pd.DataFrame:
    d = df.copy()
    c, h, lo, v = d["close"], d["high"], d["low"], d["volume"]
    d["sma20"] = ind.sma(c, 20)
    d["sma50"] = ind.sma(c, 50)
    d["sma150"] = ind.sma(c, 150)
    d["sma200"] = ind.sma(c, 200)
    d["pente200"] = d["sma200"] / d["sma200"].shift(20) - 1
    d["pente150"] = d["sma150"] / d["sma150"].shift(20) - 1
    d["atr"] = ind.atr(d)
    d["atr_pct"] = d["atr"] / c * 100
    d["rsi"] = ind.rsi(c)
    d["adx"] = ind.adx(d)
    d["haut52"] = h.rolling(252, min_periods=150).max()
    d["dist_haut52"] = c / d["haut52"] - 1
    d["haut50c"] = c.rolling(50).max().shift(1)          # plus haute clôture des 50 séances précédentes
    d["bas5"] = lo.rolling(5).min()
    d["bas10"] = lo.rolling(10).min()
    d["rsi_min5"] = d["rsi"].rolling(5).min()
    d["vol50"] = v.rolling(50).mean().shift(1)
    d["vol_rel"] = v / d["vol50"].replace(0, np.nan)
    d["base30"] = (h.rolling(30).max().shift(1) - lo.rolling(30).min().shift(1)) / c
    d["sous50_10j"] = (c < d["sma50"]).astype(float).rolling(10).sum().shift(1)
    d["perf_jour"] = (c / c.shift(1) - 1) * 100
    d["perf126"] = (c / c.shift(126) - 1) * 100
    if marche is not None and not marche.empty:
        m = marche["close"].reindex(d.index).ffill()
        d["rs126"] = d["perf126"] - (m / m.shift(126) - 1) * 100
    else:
        d["rs126"] = np.nan
    d["regime_marche"] = regime(marche, d.index)
    d["regime_secteur"] = regime(secteur, d.index)
    return d
