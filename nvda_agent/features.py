"""Assemblage de toutes les variables utilisées par la stratégie, bougie 5 min par bougie 5 min.

Règle d'or : aucune information du futur. Le contexte journalier vient de la VEILLE,
les tendances 15 min viennent de bougies 15 min CLÔTURÉES, le volume relatif compare
aux séances PRÉCÉDENTES.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .data import Marche
from .util import seance, slot, minutes_ny

COLS = ["open", "high", "low", "close", "volume"]


def _par_seance(s: pd.Series, key: np.ndarray):
    return s.groupby(key)


def _cloture_veille(df: pd.DataFrame) -> pd.Series:
    """Dernier cours de la séance précédente, aligné sur chaque bougie."""
    key = seance(df.index)
    last = df["close"].groupby(np.asarray(key)).last()
    prev = last.shift(1)
    return pd.Series(prev.reindex(key).to_numpy(), index=df.index)


def _reference(ref: pd.DataFrame | None, index: pd.DatetimeIndex, prefix: str) -> pd.DataFrame:
    """État d'un indice de référence (Nasdaq, semi-conducteurs) aligné sur les bougies NVDA."""
    cols = [f"{prefix}_chg", f"{prefix}_etat", f"{prefix}_chg30"]
    if ref is None or ref.empty:
        return pd.DataFrame(np.nan, index=index, columns=cols)
    r = ref.copy()
    key = np.asarray(seance(r.index))
    vw = ind.vwap_bandes(r)["vwap"]
    chg = (r["close"] / _cloture_veille(r) - 1) * 100
    chg30 = (r["close"] / r["close"].groupby(key).shift(6) - 1) * 100
    etat = np.where((chg > 0) & (r["close"] > vw), 1, np.where((chg < 0) & (r["close"] < vw), -1, 0))
    etat = pd.Series(etat, index=r.index).where(chg.notna())
    out = pd.DataFrame({cols[0]: chg, cols[1]: etat, cols[2]: chg30}, index=r.index)
    return out.reindex(index).ffill(limit=2)


def _contexte_journalier(daily: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    dd = daily.copy()
    dd["sma50"] = dd["close"].rolling(50).mean()
    dd["sma200"] = dd["close"].rolling(200).mean()
    dd["sma50_pente"] = dd["sma50"] - dd["sma50"].shift(10)
    dd["rsi_d"] = ind.rsi(dd["close"])
    dd["atr_d"] = ind.atr(dd)
    dd["haut20"] = dd["high"].rolling(20).max()
    dd["bas20"] = dd["low"].rolling(20).min()
    dd["vol20"] = dd["volume"].rolling(20).mean()
    ctx = dd[["sma50", "sma200", "sma50_pente", "rsi_d", "atr_d", "haut20", "bas20", "vol20",
              "close", "high", "low"]].rename(columns={"close": "veille_close", "high": "veille_haut", "low": "veille_bas"})
    ctx = ctx.assign(date=seance(ctx.index)).reset_index(drop=True).sort_values("date")
    left = pd.DataFrame({"ts": index, "date": seance(index)})
    m = pd.merge_asof(left, ctx, on="date", direction="backward", allow_exact_matches=False)
    return m.set_index("ts").drop(columns="date")


def _tendance_15m(d: pd.DataFrame) -> pd.DataFrame:
    r = ind.resample(d[COLS], "15min")
    r["ema21_15"] = ind.ema(r["close"], 21)
    r["ema50_15"] = ind.ema(r["close"], 50)
    r["atr15"] = ind.atr(r)
    r = r.join(ind.adx(r).rename(columns={"adx": "adx15", "pdi": "pdi15", "mdi": "mdi15"}))
    ecart = r["ema21_15"] - r["ema50_15"]
    seuil = 0.1 * r["atr15"]
    r["tendance15"] = np.where((ecart > seuil) & (r["close"] > r["ema50_15"]), 1,
                               np.where((ecart < -seuil) & (r["close"] < r["ema50_15"]), -1, 0))
    r["tendance15"] = r["tendance15"].where(r["ema50_15"].notna())
    r = r[["ema21_15", "ema50_15", "adx15", "tendance15"]]
    # Une bougie 5 min qui démarre à t se termine à t+5 : la dernière bougie 15 min
    # complète à ce moment a démarré au plus tard à t-10 min.
    left = pd.DataFrame({"ts": d.index, "cle": (d.index - pd.Timedelta(minutes=10)).as_unit("ns")})
    right = r.reset_index().rename(columns={"ts": "cle"})
    right["cle"] = right["cle"].dt.as_unit("ns")
    m = pd.merge_asof(left, right, on="cle", direction="backward")
    return m.set_index("ts").drop(columns="cle")


def construire(m: Marche) -> pd.DataFrame:
    d = m.nvda.copy()
    c = d["close"]
    sess = seance(d.index)
    key = np.asarray(sess)
    d["sess"] = sess
    d["slot"] = slot(d.index)
    d["minute"] = minutes_ny(d.index)

    # Tendance et momentum 5 min
    d["ema9"] = ind.ema(c, 9)
    d["ema21"] = ind.ema(c, 21)
    d["rsi"] = ind.rsi(c)
    d = d.join(ind.macd(c)).join(ind.bollinger(c)).join(ind.vwap_bandes(d))
    d["atr5"] = ind.atr(d)
    d["rvol"] = ind.rvol_horaire(d)
    d = d.join(ind.divergence(d, d["rsi"]))

    # Niveaux de la séance en cours (connus AVANT la bougie)
    g_hi = d["high"].groupby(key).cummax()
    g_lo = d["low"].groupby(key).cummin()
    d["seance_haut_av"] = g_hi.groupby(key).shift(1)
    d["seance_bas_av"] = g_lo.groupby(key).shift(1)
    d["seance_open"] = d["open"].groupby(key).transform("first")

    # Range d'ouverture = 30 premières minutes, utilisable à partir de 10h00 New York
    or_mask = d["slot"] < 6
    or_hi = d["high"].where(or_mask).groupby(key).transform("max")
    or_lo = d["low"].where(or_mask).groupby(key).transform("min")
    dispo = d["slot"] >= 6
    d["or_haut"] = or_hi.where(dispo)
    d["or_bas"] = or_lo.where(dispo)
    d["or_mil"] = ((or_hi + or_lo) / 2).where(dispo)

    # Variations
    d["cloture_veille_i"] = _cloture_veille(d)
    d["chg_jour"] = (c / d["cloture_veille_i"] - 1) * 100
    d["chg30"] = (c / c.groupby(key).shift(6) - 1) * 100

    # Contexte journalier (veille) et tendance 15 min
    d = d.join(_contexte_journalier(m.daily, d.index)).join(_tendance_15m(d))
    pente_ok = d["sma50_pente"].fillna(0)
    long_terme = np.where(d["sma200"].notna(),
                          (d["veille_close"] > d["sma50"]) & (d["sma50"] > d["sma200"]) & (pente_ok > 0),
                          (d["veille_close"] > d["sma50"]) & (pente_ok > 0))
    court_terme = np.where(d["sma200"].notna(),
                           (d["veille_close"] < d["sma50"]) & (d["sma50"] < d["sma200"]) & (pente_ok < 0),
                           (d["veille_close"] < d["sma50"]) & (pente_ok < 0))
    d["tendance_jour"] = np.where(long_terme, 1, np.where(court_terme, -1, 0))
    d["gap"] = (d["seance_open"] / d["veille_close"] - 1) * 100

    # Marché, secteur, force relative
    d = d.join(_reference(m.ref_marche, d.index, "mkt")).join(_reference(m.ref_secteur, d.index, "sec"))
    d["force_rel"] = d["chg_jour"] - d["sec_chg"]

    # VIX : niveau et variation depuis la clôture précédente
    if m.vix is not None and not m.vix.empty:
        v = m.vix["close"].sort_index()
        aligne = pd.merge_asof(pd.DataFrame({"ts": d.index.as_unit("ns")}),
                               v.rename("vix").reset_index().assign(ts=lambda x: x["ts"].dt.as_unit("ns")),
                               on="ts", direction="backward").set_index("ts")["vix"]
        d["vix"] = aligne.to_numpy()
        fin = pd.Series(d["vix"].to_numpy(), index=d.index).groupby(key).last().shift(1)
        d["vix_chg"] = (d["vix"] / fin.reindex(sess).to_numpy() - 1) * 100
    else:
        d["vix"] = np.nan
        d["vix_chg"] = np.nan
    return d
