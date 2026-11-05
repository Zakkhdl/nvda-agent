"""Petits outils : journal et formatage des nombres à la française."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import PARIS


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


def r(x) -> str:
    if not ok(x):
        return "n/d"
    x = 0.0 if abs(x) < 0.05 else float(x)
    return f"{'+' if x > 0 else ''}{num(x, 1)} R"


def jour(ts) -> str:
    return pd.Timestamp(ts).strftime("%d/%m")
