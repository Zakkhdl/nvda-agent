"""Données de marché journalières (Yahoo Finance), ajustées des divisions d'actions et dividendes.

Chaque élément de contexte facultatif (résultats, actualités, EUR/USD) peut manquer :
l'agent continue alors sans lui.
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd

from .config import NY
from .util import log

COLS = ["open", "high", "low", "close", "volume"]


def normaliser(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    df = df[[c for c in COLS if c in df.columns]].astype(float)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(NY).tz_localize(None)
    df.index = idx.normalize().as_unit("ns")
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    df.index.name = "date"
    return df


def historique(symboles: list[str], debut: str | None = None, periode: str = "3y", essais: int = 3) -> dict[str, pd.DataFrame]:
    """Télécharge les bougies journalières de tous les symboles en un seul appel."""
    import yfinance as yf

    derniere_erreur = None
    for k in range(essais):
        try:
            brut = yf.download(list(symboles), start=debut, period=None if debut else periode, interval="1d",
                               auto_adjust=True, group_by="ticker", threads=False, progress=False)
            out = {}
            for s in symboles:
                try:
                    sub = brut[s] if isinstance(brut.columns, pd.MultiIndex) else brut
                except KeyError:
                    continue
                sub = normaliser(sub)
                if len(sub) > 0:
                    out[s] = sub
            if out:
                return out
            derniere_erreur = RuntimeError("aucune donnée reçue")
        except Exception as e:
            derniere_erreur = e
        time.sleep(3 * (k + 1))
    raise RuntimeError(f"Yahoo Finance indisponible : {derniere_erreur}")


def _safe(fn, defaut=None):
    try:
        return fn()
    except Exception as e:
        log(f"Information facultative indisponible : {e}")
        return defaut


def dates_resultats(symbole: str) -> list[str]:
    """Dates de publication des résultats (passées et à venir), format AAAA-MM-JJ."""
    def f():
        import yfinance as yf
        ed = yf.Ticker(symbole).get_earnings_dates(limit=24)
        if ed is None or ed.empty:
            return []
        idx = ed.index.tz_convert(NY) if ed.index.tz is not None else ed.index
        return sorted({t.date().isoformat() for t in idx})
    return _safe(f, [])


def eurusd() -> float | None:
    def f():
        import yfinance as yf
        d = yf.Ticker("EURUSD=X").history(period="5d", interval="1d")
        return float(d["Close"].iloc[-1])
    return _safe(f)


MOTS_MARCHE = ["nasdaq", "wall st", "wall street", "chip", "semiconductor", "fed ", "federal reserve",
               "inflation", "s&p 500", "tech stocks", "export", "earnings"]


def actualites(symbole: str, nom: str, n: int = 2) -> list[dict]:
    """Derniers titres utiles sur la société (Yahoo rattache parfois des articles hors sujet)."""
    def f():
        import yfinance as yf
        out = []
        for it in yf.Ticker(symbole).news or []:
            c = it.get("content", it)
            titre = (c.get("title") or "").strip()
            if not titre:
                continue
            bas = titre.lower()
            if not (nom.lower() in bas or symbole.lower() in bas.split()):
                continue
            source = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
            date = c.get("pubDate") or ""
            if not date and it.get("providerPublishTime"):
                date = dt.datetime.fromtimestamp(it["providerPublishTime"], dt.timezone.utc).isoformat()
            out.append({"titre": titre, "source": source, "date": date})
        out.sort(key=lambda x: x["date"], reverse=True)
        return out[:n]
    return _safe(f, [])


NOMS = {"NVDA": "Nvidia", "AMD": "AMD", "AVGO": "Broadcom", "TSM": "TSMC", "ASML": "ASML", "MU": "Micron",
        "MSFT": "Microsoft", "GOOGL": "Alphabet", "GOOG": "Alphabet", "AMZN": "Amazon", "META": "Meta",
        "AAPL": "Apple", "TSLA": "Tesla", "NFLX": "Netflix", "QCOM": "Qualcomm", "INTC": "Intel", "ARM": "Arm",
        "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA", "MRVL": "Marvell", "ORCL": "Oracle",
        "CRM": "Salesforce", "ADBE": "Adobe", "PLTR": "Palantir", "SMCI": "Supermicro"}


def nom(symbole: str) -> str:
    return NOMS.get(symbole, symbole)
