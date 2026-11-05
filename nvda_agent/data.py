"""Récupération des données de marché.

Sources :
- Bougies 5 min et journalières : Twelve Data si une clé est fournie, sinon Yahoo Finance.
  Bascule automatique sur Yahoo si Twelve Data échoue.
- Contexte (VIX, futures Nasdaq, pré-marché, EUR/USD, date de résultats, actualités) : Yahoo Finance.
  Chaque élément de contexte est facultatif : s'il manque, l'agent continue sans lui.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
import requests

from .config import NY, Config
from .util import log

COLS = ["open", "high", "low", "close", "volume"]


def normaliser(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[COLS].astype(float)
    if df.index.tz is None:
        df.index = df.index.tz_localize(NY)
    else:
        df.index = df.index.tz_convert(NY)
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    df.index.name = "ts"
    return df


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------
def yahoo(symbol: str, interval: str, period: str, prepost: bool = False) -> pd.DataFrame:
    import yfinance as yf

    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, prepost=prepost)
    if df is None or df.empty:
        raise RuntimeError(f"Yahoo Finance : aucune donnée pour {symbol} ({interval})")
    return normaliser(df)


# ---------------------------------------------------------------------------
# Twelve Data
# ---------------------------------------------------------------------------
def twelvedata(symbol: str, interval: str, size: int, key: str) -> pd.DataFrame:
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": interval, "outputsize": size,
                "timezone": "America/New_York", "apikey": key},
        timeout=30,
    )
    j = r.json()
    if j.get("status") != "ok" or not j.get("values"):
        raise RuntimeError(f"Twelve Data ({symbol}) : {j.get('message', 'réponse vide')}")
    df = pd.DataFrame(j["values"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("datetime")))
    return normaliser(df)


def bougies(symbol: str, cfg: Config, intervalle: str) -> tuple[pd.DataFrame, str]:
    """intervalle : '5m' (≈60 séances) ou '1d' (≈2 ans). Renvoie (données, source)."""
    erreurs = []
    if cfg.twelvedata_key:
        try:
            if intervalle == "5m":
                return twelvedata(symbol, "5min", 5000, cfg.twelvedata_key), "Twelve Data"
            return twelvedata(symbol, "1day", 500, cfg.twelvedata_key), "Twelve Data"
        except Exception as e:
            erreurs.append(str(e))
            log(f"Twelve Data indisponible pour {symbol}, bascule sur Yahoo : {e}")
    try:
        if intervalle == "5m":
            return yahoo(symbol, "5m", "60d"), "Yahoo Finance"
        return yahoo(symbol, "1d", "2y"), "Yahoo Finance"
    except Exception as e:
        erreurs.append(str(e))
    raise RuntimeError(" | ".join(erreurs))


# ---------------------------------------------------------------------------
# Contexte facultatif
# ---------------------------------------------------------------------------
def _safe(fn, defaut=None):
    try:
        return fn()
    except Exception as e:
        log(f"Contexte facultatif indisponible : {e}")
        return defaut


def vix() -> pd.DataFrame | None:
    return _safe(lambda: yahoo("^VIX", "5m", "60d"))


def variation_jour(symbol: str) -> float | None:
    """Variation en % de la dernière séance journalière vs la précédente (futures, devises)."""
    def f():
        d = yahoo(symbol, "1d", "5d")
        return float((d["close"].iloc[-1] / d["close"].iloc[-2] - 1) * 100)
    return _safe(f)


def dernier_cours(symbol: str) -> float | None:
    return _safe(lambda: float(yahoo(symbol, "1d", "5d")["close"].iloc[-1]))


def premarche(symbol: str) -> pd.DataFrame | None:
    return _safe(lambda: yahoo(symbol, "5m", "1d", prepost=True))


def dates_resultats(symbol: str) -> list[str]:
    """Dates de publication des résultats (passées et à venir), au format AAAA-MM-JJ."""
    def f():
        import yfinance as yf
        ed = yf.Ticker(symbol).get_earnings_dates(limit=12)
        if ed is None or ed.empty:
            return []
        idx = ed.index.tz_convert(NY) if ed.index.tz is not None else ed.index
        return sorted({t.date().isoformat() for t in idx})
    return _safe(f, [])


MOTS_SOCIETE = {"NVDA": ["nvidia", "nvda", "jensen huang", "blackwell", "rubin"]}
MOTS_MARCHE = ["nasdaq", "wall st", "wall street", "chip", "semiconductor", "fed ", "federal reserve",
               "inflation", "s&p 500", "tech stocks", "export"]


def actualites(symbol: str, n: int = 3) -> list[dict]:
    """Derniers titres utiles : d'abord ceux qui parlent de la société, puis ceux sur le marché.
    Les articles hors sujet que Yahoo rattache parfois au titre sont écartés."""
    def f():
        import yfinance as yf
        items = yf.Ticker(symbol).news or []
        out = []
        for it in items:
            c = it.get("content", it)
            titre = c.get("title")
            if not titre:
                continue
            source = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
            date = c.get("pubDate")
            if not date and it.get("providerPublishTime"):
                date = dt.datetime.fromtimestamp(it["providerPublishTime"], dt.timezone.utc).isoformat()
            tickers = {t.get("symbol") for t in ((c.get("finance") or {}).get("stockTickers") or []) if isinstance(t, dict)}
            bas = titre.lower()
            direct = symbol in tickers and any(m in bas for m in MOTS_SOCIETE.get(symbol, [symbol.lower()]))
            marche = any(m in bas for m in MOTS_MARCHE)
            if direct or marche:
                out.append({"titre": titre.strip(), "source": source, "date": date or "", "prio": 0 if direct else 1})
        out.sort(key=lambda x: x["date"], reverse=True)
        out.sort(key=lambda x: x["prio"])
        return out[:n]
    return _safe(f, [])


@dataclass
class Marche:
    """Tout ce dont la stratégie a besoin pour une passe."""
    nvda: pd.DataFrame
    daily: pd.DataFrame
    ref_marche: pd.DataFrame | None
    ref_secteur: pd.DataFrame | None
    vix: pd.DataFrame | None
    source: str
    infos: dict = field(default_factory=dict)  # pré-marché, futures, eurusd, news...


def charger(cfg: Config, extras: bool = True) -> Marche:
    nvda, src = bougies(cfg.symbol, cfg, "5m")
    daily, _ = bougies(cfg.symbol, cfg, "1d")
    ref_m = _safe(lambda: bougies(cfg.marche, cfg, "5m")[0])
    ref_s = _safe(lambda: bougies(cfg.secteur, cfg, "5m")[0])
    v = vix() if extras else None
    return Marche(nvda=nvda, daily=daily, ref_marche=ref_m, ref_secteur=ref_s, vix=v, source=src)
