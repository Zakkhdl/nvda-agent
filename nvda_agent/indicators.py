"""Indicateurs techniques. Toutes les fonctions sont causales : la valeur à la bougie t
n'utilise que les bougies jusqu'à t inclus (testé dans tests/test_agent.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .util import seance, slot


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + gain / perte.replace(0, np.nan))
    return out.where(perte != 0, 100.0).where(gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), "pdi": pdi, "mdi": mdi})


def macd(close: pd.Series) -> pd.DataFrame:
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    return pd.DataFrame({"macd": line, "macd_sig": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return pd.DataFrame({"bb_up": mid + k * sd, "bb_lo": mid - k * sd})


def vwap_bandes(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP de séance et écart-type pondéré par le volume (bandes ±1 et ±2)."""
    key = np.asarray(seance(df.index))
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"]
    cv = v.groupby(key).cumsum().replace(0, np.nan)
    vwap = (tp * v).groupby(key).cumsum() / cv
    var = (tp * tp * v).groupby(key).cumsum() / cv - vwap * vwap
    sd = np.sqrt(var.clip(lower=0))
    return pd.DataFrame({"vwap": vwap, "vwap_sd": sd})


def rvol_horaire(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Volume relatif à la normale de la MÊME heure (médiane des séances précédentes).
    Indispensable car le volume intraday suit une courbe en U (fort à l'ouverture et à la clôture)."""
    sess = seance(df.index)
    sl = slot(df.index)
    tab = pd.DataFrame({"sess": sess, "slot": sl, "v": df["volume"].to_numpy()})
    piv = tab.pivot_table(index="sess", columns="slot", values="v", aggfunc="last")
    base = piv.rolling(lookback, min_periods=3).median().shift(1)
    ri = base.index.get_indexer(sess)
    ci = base.columns.get_indexer(sl)
    arr = base.to_numpy()
    vals = np.full(len(df), np.nan)
    m = (ri >= 0) & (ci >= 0)
    vals[m] = arr[ri[m], ci[m]]
    vals[vals <= 0] = np.nan
    return pd.Series(df["volume"].to_numpy() / vals, index=df.index)


def resample(df: pd.DataFrame, regle: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(regle, label="left", closed="left").agg(agg).dropna(subset=["close"])


def divergence(df: pd.DataFrame, rsi_s: pd.Series, court: int = 6, long_: int = 18, ecart: float = 3.0) -> pd.DataFrame:
    """Divergence RSI approximée : nouveau plus bas (haut) de prix sans nouveau plus bas (haut) du RSI."""
    low_c = df["low"].rolling(court).min()
    low_p = df["low"].shift(court).rolling(long_).min()
    rsi_c_min = rsi_s.rolling(court).min()
    rsi_p_min = rsi_s.shift(court).rolling(long_).min()
    high_c = df["high"].rolling(court).max()
    high_p = df["high"].shift(court).rolling(long_).max()
    rsi_c_max = rsi_s.rolling(court).max()
    rsi_p_max = rsi_s.shift(court).rolling(long_).max()
    return pd.DataFrame({
        "div_haussiere": (low_c < low_p) & (rsi_c_min > rsi_p_min + ecart),
        "div_baissiere": (high_c > high_p) & (rsi_c_max < rsi_p_max - ecart),
    })
