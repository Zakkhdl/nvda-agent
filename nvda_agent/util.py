"""Petits outils : journal, formatage des nombres à la française, temps de séance."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import NY, PARIS

BAR = pd.Timedelta(minutes=5)
BARS_SEANCE = 78  # 6h30 / 5 min


def log(msg: str) -> None:
    now = dt.datetime.now(PARIS).strftime("%d/%m %H:%M:%S")
    print(f"[{now} Paris] {msg}", flush=True)


def ok(x) -> bool:
    try:
        return x is not None and bool(np.isfinite(float(x)))
    except (TypeError, ValueError):
        return False


def num(x, d: int = 2) -> str:
    if not ok(x):
        return "n/d"
    return f"{float(x):,.{d}f}".replace(",", " ").replace(".", ",")


def usd(x, d: int = 2) -> str:
    return "n/d" if not ok(x) else f"{num(x, d)} $"


def pct(x, d: int = 1, signe: bool = True) -> str:
    if not ok(x):
        return "n/d"
    s = num(x, d)
    return f"+{s} %" if signe and float(x) > 0 else f"{s} %"


def heure_paris(ts: pd.Timestamp) -> str:
    return ts.tz_convert(PARIS).strftime("%Hh%M")


def seance(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Date de séance (New York) sans fuseau, pour regrouper les bougies par jour."""
    if idx.tz is not None:
        idx = idx.tz_convert(NY)
    return idx.normalize().tz_localize(None).as_unit("ns")


def slot(idx: pd.DatetimeIndex) -> np.ndarray:
    """Numéro de la bougie 5 min dans la séance : 0 = 9h30 New York, 77 = 15h55."""
    t = idx.tz_convert(NY)
    minutes = t.hour * 60 + t.minute - (9 * 60 + 30)
    return (np.asarray(minutes) // 5).astype(int)


def minutes_ny(idx: pd.DatetimeIndex) -> np.ndarray:
    t = idx.tz_convert(NY)
    return np.asarray(t.hour * 60 + t.minute)
