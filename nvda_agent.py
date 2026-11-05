#!/usr/bin/env python3
"""
Agent de signaux techniques NVIDIA (NVDA)

Ce que fait l'agent :
- Tourne toutes les 5 minutes pendant la séance US (15h30 à 22h00 heure de Paris).
- Calcule RSI, MACD, bandes de Bollinger, VWAP, volume et tendance de fond journalière.
- Additionne les signaux dans un score de confluence (0 à 10) côté achat et côté vente.
- T'envoie une alerte quand le score dépasse le seuil ET qu'un vrai déclencheur apparaît.
- T'envoie un point d'ouverture chaque jour et une alerte en cas de mouvement brusque.

Signaux techniques uniquement. Ce n'est pas un conseil en investissement.

Usage :
  python nvda_agent.py              une passe (GitHub Actions ou tâche planifiée)
  python nvda_agent.py --loop       tourne en continu sur ton PC, toutes les 5 minutes
  python nvda_agent.py --test       envoie une notification de test
  python nvda_agent.py --backtest   rejoue les ~60 dernières séances et mesure les signaux
  python nvda_agent.py --force      ignore les horaires de marché (pour tester)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Réglages (tous modifiables par variables d'environnement)
# ---------------------------------------------------------------------------
SYMBOL = os.getenv("SYMBOL", "NVDA").strip() or "NVDA"
SEUIL_SCORE = int(os.getenv("SEUIL_SCORE", "5") or 5)            # score mini pour alerter (sur 10)
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "60") or 60)         # délai mini entre 2 alertes du même type
SEUIL_MOUVEMENT = float(os.getenv("SEUIL_MOUVEMENT", "2.5") or 2.5)  # variation en % sur 30 min
STATE_FILE = os.getenv("STATE_FILE", "state.json")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_SERVER = (os.getenv("NTFY_SERVER", "") or "https://ntfy.sh").strip().rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()

NY = ZoneInfo("America/New_York")
PARIS = ZoneInfo("Europe/Paris")
BAR = pd.Timedelta(minutes=5)
BARS_PAR_SEANCE = 78  # 6h30 de séance / 5 min


# ---------------------------------------------------------------------------
# Outils d'affichage
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    now = dt.datetime.now(PARIS).strftime("%d/%m %H:%M:%S")
    print(f"[{now} Paris] {msg}", flush=True)


def ok(x) -> bool:
    try:
        return x is not None and np.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def num(x, d: int = 2) -> str:
    if not ok(x):
        return "n/d"
    s = f"{float(x):,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


def usd(x) -> str:
    return "n/d" if not ok(x) else f"{num(x)} $"


def pct(x, d: int = 1, signe: bool = True) -> str:
    if not ok(x):
        return "n/d"
    s = num(x, d)
    return f"+{s} %" if signe and float(x) > 0 else f"{s} %"


def heure_paris(ts: pd.Timestamp) -> str:
    return ts.tz_convert(PARIS).strftime("%Hh%M")


# ---------------------------------------------------------------------------
# Données de marché
# ---------------------------------------------------------------------------
def _normaliser(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df.index.name = "ts"
    return df


def fetch_yahoo(interval: str, period: str) -> pd.DataFrame:
    import yfinance as yf  # import ici pour ne pas l'exiger si Twelve Data suffit

    df = yf.Ticker(SYMBOL).history(period=period, interval=interval, auto_adjust=False, prepost=False)
    if df is None or df.empty:
        raise RuntimeError(f"Yahoo Finance n'a renvoyé aucune donnée ({interval})")
    df.index = df.index.tz_localize(NY) if df.index.tz is None else df.index.tz_convert(NY)
    return _normaliser(df)


def fetch_twelvedata(interval: str, size: int) -> pd.DataFrame:
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": SYMBOL,
            "interval": interval,
            "outputsize": size,
            "timezone": "America/New_York",
            "apikey": TWELVEDATA_API_KEY,
        },
        timeout=30,
    )
    j = r.json()
    if j.get("status") != "ok" or not j.get("values"):
        raise RuntimeError(f"Twelve Data : {j.get('message', 'réponse vide')}")
    df = pd.DataFrame(j["values"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("datetime"))).tz_localize(NY)
    return _normaliser(df)


def fetch_data(backtest: bool = False):
    """Renvoie (bougies 5 min, bougies journalières, nom de la source)."""
    sources = []
    if TWELVEDATA_API_KEY:
        sources.append("Twelve Data")
    sources.append("Yahoo Finance")
    erreurs = []
    for src in sources:
        try:
            if src == "Twelve Data":
                intra = fetch_twelvedata("5min", 5000 if backtest else 400)
                daily = fetch_twelvedata("1day", 400)
            else:
                intra = fetch_yahoo("5m", "60d" if backtest else "5d")
                daily = fetch_yahoo("1d", "2y")
            return intra, daily, src
        except Exception as e:  # on bascule sur la source suivante
            erreurs.append(f"{src} : {e}")
            log(f"Source indisponible. {src} : {e}")
    raise RuntimeError(" | ".join(erreurs))


def bougies_cloturees(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Retire la bougie en cours de formation."""
    return df[df.index + BAR <= now]


# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------
def day_key(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Date de séance (heure de New York), sans fuseau, pour regrouper par jour."""
    if idx.tz is not None:
        idx = idx.tz_convert(NY)
    return idx.normalize().tz_localize(None).as_unit("ns")


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / perte.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(perte != 0, 100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def vwap_seance(d: pd.DataFrame) -> pd.Series:
    key = np.asarray(day_key(d.index))
    tp = (d["high"] + d["low"] + d["close"]) / 3
    pv = (tp * d["volume"]).groupby(key).cumsum()
    vv = d["volume"].groupby(key).cumsum()
    return pv / vv.replace(0, np.nan)


def build_features(intra: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    d = intra.copy()
    c = d["close"]
    key = np.asarray(day_key(d.index))

    d["rsi"] = rsi(c)
    d["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["macd_sig"] = d["macd"].ewm(span=9, adjust=False).mean()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    d["bb_up"] = mid + 2 * sd
    d["bb_lo"] = mid - 2 * sd
    d["vwap"] = vwap_seance(d)
    d["vol_ratio"] = d["volume"] / d["volume"].rolling(20).mean().replace(0, np.nan)
    d["chg30"] = (c / c.groupby(key).shift(6) - 1) * 100  # variation sur 30 min, même séance

    # Contexte journalier : valeurs de la VEILLE (aucune info du futur)
    dd = daily.copy()
    dd["sma50"] = dd["close"].rolling(50).mean()
    dd["sma200"] = dd["close"].rolling(200).mean()
    dd["rsi_d"] = rsi(dd["close"])
    dd["atr_d"] = atr(dd)
    ctx = dd[["sma50", "sma200", "rsi_d", "atr_d", "close", "high", "low"]].rename(
        columns={"close": "prev_close", "high": "prev_high", "low": "prev_low"}
    )
    ctx = ctx.assign(date=day_key(ctx.index)).reset_index(drop=True).sort_values("date")
    left = pd.DataFrame({"ts": d.index, "date": day_key(d.index)})
    m = pd.merge_asof(left, ctx, on="date", direction="backward", allow_exact_matches=False)
    m = m.set_index("ts").drop(columns="date")
    return d.join(m)


# ---------------------------------------------------------------------------
# Score de confluence
# ---------------------------------------------------------------------------
def score(d: pd.DataFrame, seuil: int | None = None):
    """Renvoie (tableau avec scores et signal, conditions détaillées)."""
    seuil = SEUIL_SCORE if seuil is None else seuil
    p = d.shift(1)
    sday = pd.Series(day_key(d.index), index=d.index)
    meme_seance = sday.eq(sday.shift(1))
    verte = d["close"] > d["open"]
    rouge = d["close"] < d["open"]
    vol_fort = d["vol_ratio"] >= 1.5
    haussier = (d["close"] > d["sma50"]) & (d["sma50"] > d["sma200"])
    baissier = (d["close"] < d["sma50"]) & (d["sma50"] < d["sma200"])

    # (raison, poids, condition). Poids 2 = déclencheur. Poids négatif = pénalité.
    conds = {
        "ACHAT": [
            ("RSI 5 min repasse au-dessus de 30 (sortie de survente)", 2, (p["rsi"] < 30) & (d["rsi"] >= 30)),
            ("RSI 5 min en survente (sous 30)", 1, d["rsi"] < 30),
            ("MACD croise sa ligne de signal à la hausse", 2, (p["macd"] <= p["macd_sig"]) & (d["macd"] > d["macd_sig"])),
            ("Rebond sur la bande de Bollinger basse", 2, (p["close"] < p["bb_lo"]) & (d["close"] >= d["bb_lo"])),
            ("Prix sous la bande de Bollinger basse", 1, d["close"] < d["bb_lo"]),
            ("Prix repasse au-dessus du VWAP", 1, meme_seance & (p["close"] <= p["vwap"]) & (d["close"] > d["vwap"])),
            ("Bougie verte avec volume fort (x1,5)", 1, verte & vol_fort),
            ("Tendance de fond haussière (prix > MM50 > MM200)", 1, haussier),
            ("RSI journalier bas (sous 35)", 1, d["rsi_d"] < 35),
            ("Va contre la tendance de fond baissière", -1, baissier),
        ],
        "VENTE": [
            ("RSI 5 min repasse sous 70 (sortie de surachat)", 2, (p["rsi"] > 70) & (d["rsi"] <= 70)),
            ("RSI 5 min en surachat (au-dessus de 70)", 1, d["rsi"] > 70),
            ("MACD croise sa ligne de signal à la baisse", 2, (p["macd"] >= p["macd_sig"]) & (d["macd"] < d["macd_sig"])),
            ("Rejet sur la bande de Bollinger haute", 2, (p["close"] > p["bb_up"]) & (d["close"] <= d["bb_up"])),
            ("Prix au-dessus de la bande de Bollinger haute", 1, d["close"] > d["bb_up"]),
            ("Prix passe sous le VWAP", 1, meme_seance & (p["close"] >= p["vwap"]) & (d["close"] < d["vwap"])),
            ("Bougie rouge avec volume fort (x1,5)", 1, rouge & vol_fort),
            ("Tendance de fond baissière (prix < MM50 < MM200)", 1, baissier),
            ("RSI journalier élevé (au-dessus de 70)", 1, d["rsi_d"] > 70),
            ("Va contre la tendance de fond haussière", -1, haussier),
        ],
    }
    conds = {s: [(n, w, c.fillna(False).astype(bool)) for n, w, c in lst] for s, lst in conds.items()}

    out = pd.DataFrame(index=d.index)
    for side, lst in conds.items():
        out[f"score_{side.lower()}"] = sum(w * c.astype(int) for _, w, c in lst)
        out[f"trig_{side.lower()}"] = np.logical_or.reduce([c.to_numpy() for _, w, c in lst if w >= 2])

    bs, ss = out["score_achat"], out["score_vente"]
    achat = (bs >= seuil) & out["trig_achat"] & (bs > ss)
    vente = (ss >= seuil) & out["trig_vente"] & (ss > bs)
    out["signal"] = np.select([achat.to_numpy(), vente.to_numpy()], ["ACHAT", "VENTE"], default="")
    return d.join(out), conds


def raisons(conds, side: str, ts) -> tuple[list[str], list[str]]:
    pos = [n for n, w, c in conds[side] if w > 0 and bool(c.loc[ts])]
    neg = [n for n, w, c in conds[side] if w < 0 and bool(c.loc[ts])]
    return pos, neg


def tendance(row) -> str:
    c, m50, m200 = row["prev_close"], row["sma50"], row["sma200"]
    if not (ok(c) and ok(m50) and ok(m200)):
        return "indéterminée (historique trop court)"
    if c > m50 > m200:
        return "haussière (prix > MM50 > MM200)"
    if c < m50 < m200:
        return "baissière (prix < MM50 < MM200)"
    return "neutre (moyennes mobiles mélangées)"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def msg_signal(side: str, ts, row, conds) -> tuple[str, str]:
    pos, neg = raisons(conds, side, ts)
    sc = int(row[f"score_{side.lower()}"])
    autre = int(row["score_vente" if side == "ACHAT" else "score_achat"])
    titre = f"{SYMBOL} : signal {side.lower()} (score {sc}/10)"
    atr_pct = row["atr_d"] / row["close"] * 100 if ok(row["atr_d"]) else np.nan
    lignes = [
        f"Prix : {usd(row['close'])} à {heure_paris(ts + BAR)}",
        "Pourquoi :",
        *[f"• {r}" for r in pos],
    ]
    if neg:
        lignes.append(f"Attention : {', '.join(neg).lower()}")
    lignes += [
        f"Score opposé : {max(autre, 0)}/10",
        f"RSI 5 min : {num(row['rsi'], 1)} | VWAP : {usd(row['vwap'])}",
        f"Volatilité moyenne (ATR) : {usd(row['atr_d'])} soit {pct(atr_pct, 1, signe=False)}",
        f"Veille : haut {usd(row['prev_high'])}, bas {usd(row['prev_low'])}",
        "Signal technique, pas un conseil.",
    ]
    return titre, "\n".join(lignes)


def msg_mouvement(ts, row) -> tuple[str, str]:
    sens = "monte" if row["chg30"] > 0 else "baisse"
    titre = f"{SYMBOL} {sens} vite : {pct(row['chg30'])} en 30 min"
    corps = "\n".join([
        f"Prix : {usd(row['close'])} à {heure_paris(ts + BAR)}",
        f"Volume : x{num(row['vol_ratio'], 1)} vs moyenne",
        f"RSI 5 min : {num(row['rsi'], 1)} | VWAP : {usd(row['vwap'])}",
        "Regarde l'actu avant d'agir (annonce, résultats, macro).",
    ])
    return titre, corps


def msg_ouverture(rows_jour: pd.DataFrame) -> tuple[str, str]:
    first, last = rows_jour.iloc[0], rows_jour.iloc[-1]
    gap = (first["open"] / first["prev_close"] - 1) * 100 if ok(first["prev_close"]) else np.nan
    atr_pct = last["atr_d"] / last["prev_close"] * 100 if ok(last["atr_d"]) and ok(last["prev_close"]) else np.nan
    titre = f"{SYMBOL} : point d'ouverture du {rows_jour.index[0].strftime('%d/%m')}"
    corps = "\n".join([
        f"Prix : {usd(last['close'])} | Écart à l'ouverture : {pct(gap)}",
        f"Clôture veille : {usd(first['prev_close'])}",
        f"Veille : haut {usd(first['prev_high'])}, bas {usd(first['prev_low'])}",
        f"MM50 : {usd(first['sma50'])} | MM200 : {usd(first['sma200'])}",
        f"Tendance de fond : {tendance(first)}",
        f"RSI journalier : {num(first['rsi_d'], 0)}",
        f"Volatilité moyenne (ATR) : {usd(first['atr_d'])} soit {pct(atr_pct, 1, signe=False)} par jour",
    ])
    return titre, corps


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
EMOJI = {"green_circle": "🟢", "red_circle": "🔴", "zap": "⚡", "sunrise": "🌅",
         "warning": "⚠️", "white_check_mark": "✅"}


def notify(titre: str, corps: str, tag: str = "", priorite: int = 4) -> bool:
    envoye = False
    if NTFY_TOPIC:
        try:
            r = requests.post(
                NTFY_SERVER,
                json={"topic": NTFY_TOPIC, "title": titre, "message": corps,
                      "priority": priorite, "tags": [tag] if tag else []},
                timeout=15,
            )
            r.raise_for_status()
            envoye = True
        except Exception as e:
            log(f"Échec de l'envoi ntfy : {e}")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            texte = f"{EMOJI.get(tag, '')} {titre}".strip() + "\n\n" + corps
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texte, "disable_web_page_preview": True},
                timeout=15,
            )
            r.raise_for_status()
            envoye = True
        except Exception as e:
            log(f"Échec de l'envoi Telegram : {e}")
    log(f"ALERTE {'envoyée' if envoye else 'non envoyée (aucun canal configuré)'} : {titre}\n{corps}")
    return envoye


# ---------------------------------------------------------------------------
# État (évite les alertes en double)
# ---------------------------------------------------------------------------
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def cooldown_ok(state: dict, cle: str, ts: pd.Timestamp) -> bool:
    dernier = state.get("last_alert", {}).get(cle)
    return not dernier or ts - pd.Timestamp(dernier) >= pd.Timedelta(minutes=COOLDOWN_MIN)


def marque_alerte(state: dict, cle: str, ts: pd.Timestamp) -> None:
    state.setdefault("last_alert", {})[cle] = ts.isoformat()


# ---------------------------------------------------------------------------
# Une passe de l'agent
# ---------------------------------------------------------------------------
def marche_ouvert(now: dt.datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return dt.time(9, 35) <= now.time() <= dt.time(16, 10)


def traiter(sig: pd.DataFrame, conds, state: dict, src: str, now: pd.Timestamp) -> int:
    """Analyse les nouvelles bougies et envoie les alertes. Renvoie le nombre d'alertes."""
    nb = 0
    ts_last = sig.index[-1]
    last = sig.iloc[-1]
    log(
        f"{SYMBOL} {usd(last['close'])} (bougie {heure_paris(ts_last)}) | RSI {num(last['rsi'], 1)} | "
        f"MACD {num(last['macd'], 3)} / {num(last['macd_sig'], 3)} | score achat {int(last['score_achat'])} "
        f"vente {int(last['score_vente'])} | seuil {SEUIL_SCORE} | source {src}"
    )

    # Point d'ouverture, une fois par jour
    jour = day_key(sig.index[-1:])[0]
    if day_key(pd.DatetimeIndex([now]))[0] == jour and state.get("brief_date") != jour.date().isoformat():
        rows_jour = sig[day_key(sig.index) == jour]
        titre, corps = msg_ouverture(rows_jour)
        notify(titre, corps, tag="sunrise", priorite=3)
        state["brief_date"] = jour.date().isoformat()
        nb += 1

    # Bougies pas encore analysées (30 min max de rattrapage)
    last_bar = state.get("last_bar")
    nouvelles = sig[sig.index > pd.Timestamp(last_bar)] if last_bar else sig.tail(1)
    nouvelles = nouvelles.tail(6)

    for side, tag in (("ACHAT", "green_circle"), ("VENTE", "red_circle")):
        hits = nouvelles[nouvelles["signal"] == side]
        if hits.empty:
            continue
        ts = hits.index[-1]
        if not cooldown_ok(state, side, ts):
            log(f"Signal {side.lower()} ignoré : dernière alerte il y a moins de {COOLDOWN_MIN} min.")
            continue
        titre, corps = msg_signal(side, ts, hits.iloc[-1], conds)
        notify(titre, corps, tag=tag, priorite=5)
        marque_alerte(state, side, ts)
        nb += 1

    brusques = nouvelles[nouvelles["chg30"].abs() >= SEUIL_MOUVEMENT]
    if not brusques.empty:
        ts = brusques.index[-1]
        if cooldown_ok(state, "MOUVEMENT", ts):
            titre, corps = msg_mouvement(ts, brusques.iloc[-1])
            notify(titre, corps, tag="zap", priorite=4)
            marque_alerte(state, "MOUVEMENT", ts)
            nb += 1

    state["last_bar"] = ts_last.isoformat()
    return nb


def run_once(force: bool = False, now: dt.datetime | None = None, fetch=fetch_data) -> int:
    now = now or dt.datetime.now(NY)
    now_ts = pd.Timestamp(now).tz_convert(NY)
    state = load_state()
    nb = 0
    try:
        if not force and not marche_ouvert(now_ts.to_pydatetime()):
            log(f"Marché fermé ({now_ts.tz_convert(PARIS):%a %d/%m %Hh%M} Paris). Rien à faire.")
            return 0
        intra, daily, src = fetch()
        intra = bougies_cloturees(intra, now_ts)
        if len(intra) < 60:
            raise RuntimeError(f"pas assez de bougies 5 min ({len(intra)})")
        sig, conds = score(build_features(intra, daily))
        if state.get("errors", 0) >= 3:
            notify(f"Agent {SYMBOL} : données rétablies", "L'agent fonctionne de nouveau.", tag="white_check_mark", priorite=2)
        state["errors"] = 0
        nb = traiter(sig, conds, state, src, now_ts)
    except Exception as e:
        state["errors"] = state.get("errors", 0) + 1
        log(f"Erreur ({state['errors']} d'affilée) : {e}")
        if state["errors"] == 3:
            notify(f"Agent {SYMBOL} : problème de données",
                   f"3 échecs d'affilée. Pas d'alerte possible tant que ça dure.\nDernière erreur : {e}",
                   tag="warning", priorite=3)
    finally:
        save_state(state)
    return nb


def boucle(force: bool) -> None:
    log(f"Agent {SYMBOL} lancé. Une analyse toutes les 5 minutes. Ctrl+C pour arrêter.")
    while True:
        try:
            run_once(force=force)
        except Exception as e:  # ne jamais arrêter la boucle
            log(f"Erreur inattendue : {e}")
        attente = 300 - (time.time() % 300) + 20  # 20 s après chaque clôture de bougie
        time.sleep(attente)


def test_notification() -> None:
    if not (NTFY_TOPIC or (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)):
        log("Aucun canal configuré. Renseigne NTFY_TOPIC ou TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.")
        sys.exit(1)
    if notify(f"Test agent {SYMBOL}", "Si tu lis ce message, les alertes fonctionnent.", tag="white_check_mark", priorite=3):
        log("Notification de test envoyée.")
    else:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Backtest : les signaux passés ont-ils eu raison ?
# ---------------------------------------------------------------------------
def filtre_cooldown(index, minutes: int) -> list:
    garde, dernier = [], None
    for ts in index:
        if dernier is None or ts - dernier >= pd.Timedelta(minutes=minutes):
            garde.append(ts)
            dernier = ts
    return garde


def backtest(fetch=fetch_data, csv_path: str = "signaux_backtest.csv") -> pd.DataFrame:
    intra, daily, src = fetch(backtest=True)
    feats = build_features(intra, daily)
    close = feats["close"]
    f1h = (close.shift(-12) / close - 1) * 100
    f1j = (close.shift(-BARS_PAR_SEANCE) / close - 1) * 100
    nb_seances = len(np.unique(day_key(feats.index)))

    print(f"\nBacktest {SYMBOL} sur {nb_seances} séances ({src}, bougies 5 min)")
    print(f"Du {feats.index[0]:%d/%m/%Y} au {feats.index[-1]:%d/%m/%Y}. Cooldown {COOLDOWN_MIN} min.\n")
    print("Référence (au hasard) :")
    print(f"  le cours monte 1 h après dans {num((f1h > 0).mean() * 100, 0)} % des cas, "
          f"1 séance après dans {num((f1j > 0).mean() * 100, 0)} % des cas.\n")

    entete = f"{'Seuil':<6}{'Sens':<7}{'Signaux':>8}{'Juste 1h':>10}{'Moy. 1h':>10}{'Juste 1 séance':>16}{'Moy. 1 séance':>15}"
    print(entete)
    print("-" * len(entete))
    lignes_csv = []
    for seuil in (4, 5, 6, 7):
        sig, conds = score(feats, seuil)
        for side, sens in (("ACHAT", 1), ("VENTE", -1)):
            ts_list = filtre_cooldown(sig.index[sig["signal"] == side], COOLDOWN_MIN)
            r1 = (f1h.loc[ts_list] * sens).dropna()
            rj = (f1j.loc[ts_list] * sens).dropna()
            if len(ts_list) == 0:
                print(f"{seuil:<6}{side:<7}{0:>8}{'-':>10}{'-':>10}{'-':>16}{'-':>15}")
                continue
            print(
                f"{seuil:<6}{side:<7}{len(ts_list):>8}"
                f"{pct((r1 > 0).mean() * 100 if len(r1) else np.nan, 0, False):>10}"
                f"{pct(r1.mean(), 2):>10}"
                f"{pct((rj > 0).mean() * 100 if len(rj) else np.nan, 0, False):>16}"
                f"{pct(rj.mean(), 2):>15}"
            )
            if seuil == SEUIL_SCORE:
                for ts in ts_list:
                    pos, neg = raisons(conds, side, ts)
                    lignes_csv.append({
                        "date_paris": (ts + BAR).tz_convert(PARIS).strftime("%Y-%m-%d %H:%M"),
                        "signal": side, "prix": round(float(close.loc[ts]), 2),
                        "score": int(sig.loc[ts, f"score_{side.lower()}"]),
                        "var_1h_%": round(float(f1h.loc[ts]), 2) if ok(f1h.loc[ts]) else None,
                        "var_1_seance_%": round(float(f1j.loc[ts]), 2) if ok(f1j.loc[ts]) else None,
                        "raisons": " | ".join(pos + neg),
                    })
    print("\n« Juste » = le cours est allé dans le sens du signal. « Moy. » = gain moyen dans le sens du signal.")
    print("Moins de 30 signaux = échantillon trop petit pour conclure. Frais et écart achat/vente non inclus.")
    out = pd.DataFrame(lignes_csv).sort_values("date_paris") if lignes_csv else pd.DataFrame()
    if csv_path and not out.empty:
        out.to_csv(csv_path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        print(f"Détail des signaux (seuil {SEUIL_SCORE}) : {csv_path}")
    return out


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=f"Agent de signaux techniques {SYMBOL}")
    ap.add_argument("--loop", action="store_true", help="tourne en continu toutes les 5 minutes")
    ap.add_argument("--test", action="store_true", help="envoie une notification de test")
    ap.add_argument("--backtest", action="store_true", help="mesure les signaux sur ~60 séances")
    ap.add_argument("--force", action="store_true", help="ignore les horaires de marché")
    a = ap.parse_args()
    if a.test:
        test_notification()
    elif a.backtest:
        backtest()
    elif a.loop:
        boucle(a.force)
    else:
        run_once(force=a.force)


if __name__ == "__main__":
    main()
