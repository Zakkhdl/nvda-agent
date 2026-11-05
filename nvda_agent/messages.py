"""Rédaction des alertes (courtes, lisibles sur iPhone)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import Config
from .strategy import SENS, nom_setup
from .util import BAR, heure_paris, num, ok, pct, usd

AVERTISSEMENT = "Signal technique, pas un conseil."


def _r(x: float) -> str:
    return f"{'+' if x > 0 else ''}{num(x, 2)} R"


def _raisons(fct: dict, row: pd.Series, s: int, code_res: int, code_mac: int,
             obstacle: float = float("nan")) -> tuple[list[str], list[str]]:
    """Transforme les points de chaque facteur en phrases. Renvoie (pour, contre)."""
    pour, contre = [], []
    sens_txt = "haussière" if s == 1 else "baissière"
    oppose_txt = "baissière" if s == 1 else "haussière"

    def ajoute(pts, txt_pour, txt_contre=None):
        if pts > 0:
            pour.append(txt_pour)
        elif pts < 0 and txt_contre:
            contre.append(txt_contre)

    ajoute(fct.get("tendance_jour", 0), f"Tendance de fond {sens_txt} (MM50 / MM200)", f"Contre la tendance de fond {oppose_txt}")
    ajoute(fct.get("tendance_15m", 0), f"Tendance 15 min {sens_txt}", f"Tendance 15 min {oppose_txt}")
    adx = row.get("adx15")
    ajoute(fct.get("adx", 0), f"Régime favorable (ADX 15 min {num(adx, 0)})", f"Régime défavorable (ADX 15 min {num(adx, 0)})")
    ajoute(fct.get("marche", 0), f"Nasdaq dans le même sens ({pct(row.get('mkt_chg'), 2)})", f"Nasdaq en sens inverse ({pct(row.get('mkt_chg'), 2)})")
    ajoute(fct.get("secteur", 0), f"Semi-conducteurs dans le même sens ({pct(row.get('sec_chg'), 2)})", f"Semi-conducteurs en sens inverse ({pct(row.get('sec_chg'), 2)})")
    ajoute(fct.get("force_relative", 0), f"NVIDIA plus forte que son secteur ({pct(row.get('force_rel'), 2)})" if s == 1
           else f"NVIDIA plus faible que son secteur ({pct(row.get('force_rel'), 2)})",
           f"NVIDIA à contre-courant de son secteur ({pct(row.get('force_rel'), 2)})")
    ajoute(fct.get("volume", 0), f"Volume x{num(row.get('rvol'), 1)} vs normale à cette heure", f"Volume faible (x{num(row.get('rvol'), 1)} vs normale)")
    ajoute(fct.get("divergence", 0), "Divergence RSI en faveur du signal")
    ajoute(fct.get("momentum", 0), "Momentum MACD qui accélère", "Momentum MACD qui faiblit")
    ajoute(fct.get("extension", 0), "", f"Prix déjà loin du VWAP ({usd(row.get('vwap'))})")
    ajoute(fct.get("rsi_extreme", 0), "", f"RSI 5 min déjà extrême ({num(row.get('rsi'), 0)})")
    obs = f" ({usd(obstacle)})" if ok(obstacle) else ""
    ajoute(fct.get("espace", 0), f"De la place jusqu'au prochain obstacle{obs}",
           f"{'Résistance' if s == 1 else 'Support'} proche avant l'objectif 1{obs}")
    ajoute(fct.get("risque", 0), "", "Stop large ou dans le bruit")
    ajoute(fct.get("horaire", 0), "", "Horaire peu fiable (ouverture, pause déjeuner ou fin de séance)")
    ajoute(fct.get("vix", 0), "Peur en hausse (VIX), favorable à la baisse", f"Marché nerveux (VIX {num(row.get('vix'), 1)})")
    if code_res:
        contre.append({1: "Résultats NVIDIA demain soir", 2: "Résultats NVIDIA ce soir après la clôture",
                       3: "Lendemain de résultats : volatilité extrême"}[code_res])
    if code_mac:
        contre.append({1: "Décision de la Fed aujourd'hui à 20h00 (Paris)", 2: "Décision de la Fed imminente ou en cours",
                       3: "Chiffre macro publié ce matin (inflation ou emploi)"}[code_mac])
    hist = fct.get("historique", 0)
    if hist > 0:
        pour.append("Configuration rentable sur les 60 dernières séances")
    elif hist < 0:
        contre.append("Configuration perdante sur les 60 dernières séances")
    return [p for p in pour if p], [c for c in contre if c]


def taille(cfg: Config, entree: float, stop: float, eurusd: float | None) -> str | None:
    if cfg.capital_eur <= 0 or not ok(eurusd):
        return None
    risque_eur = cfg.capital_eur * cfg.risque_pct / 100
    par_action = abs(entree - stop)
    if par_action <= 0:
        return None
    n = math.floor(risque_eur * eurusd / par_action)
    n = min(n, math.floor(cfg.capital_eur * eurusd / entree))
    if n <= 0:
        return f"Taille : stop trop large pour ton capital ({num(cfg.risque_pct, 1)} % de risque)"
    perte = n * par_action / eurusd
    return f"Taille indicative : {n} actions (perte au stop ≈ {num(perte, 0)} €)"


def signal(cfg: Config, a, i: int, pos: dict, stats_cle: dict | None, eurusd: float | None) -> tuple[str, str, str, int]:
    from .strategy import facteurs

    row = a.f.iloc[i]
    ts = a.f.index[i]
    s, cle, score = pos["sens"], pos["cle"], pos["score"]
    note = "A" if score >= cfg.seuil_a else "B"
    titre = f"{cfg.symbol} {SENS[s]} {note} ({int(score)}/100) : {nom_setup(cle)}"
    e, st, t1, t2 = pos["entree"], pos["stop"], pos["t1"], pos["t2"]
    rr2 = abs(t2 - e) / abs(e - st)
    lignes = [
        f"Entrée ≈ {usd(e)} ({heure_paris(ts + BAR)})",
        f"Stop {usd(st)} ({pct((st / e - 1) * 100, 2)})",
        f"Objectif 1 : {usd(t1)} (1 R) | Objectif 2 : {usd(t2)} ({num(rr2, 1)} R)",
    ]
    t = taille(cfg, e, st, eurusd)
    if t:
        lignes.append(t)
    pour, contre = _raisons(facteurs(a, cle, i), row, s, int(a.meilleur["code_res"][i]),
                            int(a.meilleur["code_mac"][i]), float(a.cand[cle]["obstacle"][i]))
    if pour:
        lignes += ["", "Pour :", *[f"• {p}" for p in pour[:6]]]
    if contre:
        lignes += ["Contre :", *[f"• {c}" for c in contre[:5]]]
    if stats_cle and stats_cle.get("n", 0) >= 5:
        lignes.append(f"Historique 60 séances : {stats_cle['n']} cas, {num(stats_cle['gagnants'], 0)} % gagnants, "
                      f"espérance {_r(stats_cle['esperance'])}")
    lignes += ["Plan : moitié à l'objectif 1 puis stop au prix d'entrée.", AVERTISSEMENT]
    tag = "green_circle" if s == 1 else "red_circle"
    return titre, "\n".join(lignes), tag, 5 if note == "A" else 4


def suivi(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    ts = pd.Timestamp(ev["ts"])
    heure = heure_paris(ts + BAR)
    if ev["type"] == "T1":
        p = ev["pos"]
        return (f"{cfg.symbol} objectif 1 atteint ({SENS[p['sens']].lower()})",
                f"{usd(ev['prix'])} à {heure}. +1 R sur la moitié.\nStop remonté au prix d'entrée : {usd(p['entree'])}.\n"
                f"Objectif 2 : {usd(p['t2'])}.", "dart", 4)
    t = ev["trade"]
    sens = SENS[t["sens"]].lower()
    motifs = {
        "T2": ("objectif 2 atteint", "trophy"),
        "STOP": ("stop touché", "x"),
        "BE": ("sortie au prix d'entrée", "handshake"),
        "FIN": ("clôture de fin de séance", "bell"),
        "INVERSE": ("signal inverse, clôture", "arrows_counterclockwise"),
    }
    txt, tag = motifs[ev["type"]]
    corps = (f"Entrée {usd(t['entree'])}, sortie {usd(t['sortie'])} à {heure}.\n"
             f"Résultat : {_r(t['R'])} (frais inclus).")
    return f"{cfg.symbol} {sens} : {txt} ({_r(t['R'])})", corps, tag, 4 if ev["type"] in ("STOP", "T2") else 3


def mouvement(cfg: Config, row: pd.Series, ts, news: list[dict]) -> tuple[str, str, str, int]:
    sens = "monte" if row["chg30"] > 0 else "chute"
    lignes = [f"{usd(row['close'])} à {heure_paris(ts + BAR)} | séance {pct(row.get('chg_jour'), 2)}",
              f"Volume x{num(row.get('rvol'), 1)} vs normale | Nasdaq {pct(row.get('mkt_chg'), 2)}",
              f"Semi-conducteurs {pct(row.get('sec_chg'), 2)}"]
    if news:
        lignes.append(f"Dernière actu : {news[0]['titre']} ({news[0]['source']})")
    lignes.append("Vérifie l'actualité avant d'agir.")
    return f"{cfg.symbol} {sens} de {pct(row['chg30'])} en 30 min", "\n".join(lignes), "zap", 4


def _biais(tj: int, prem: float | None, fut: float | None) -> str:
    score = tj + (0.5 if ok(prem) and prem > 0.5 else -0.5 if ok(prem) and prem < -0.5 else 0) \
        + (0.5 if ok(fut) and fut > 0.3 else -0.5 if ok(fut) and fut < -0.3 else 0)
    return "haussier" if score >= 1 else "baissier" if score <= -1 else "neutre"


def avant_ouverture(cfg: Config, daily_ctx: dict, prem: dict, evts: list[str], news: list[dict]) -> tuple[str, str, str, int]:
    tj = daily_ctx.get("tendance_jour", 0)
    tend = {1: "haussière", -1: "baissière", 0: "neutre"}[int(tj)]
    lignes = []
    if ok(prem.get("prix")):
        lignes.append(f"Pré-marché : {usd(prem['prix'])} ({pct(prem.get('chg'), 2)} vs clôture)")
    lignes += [
        f"Futures Nasdaq : {pct(prem.get('futures'), 2)} | VIX : {num(prem.get('vix'), 1)}",
        f"Tendance de fond : {tend} | RSI jour : {num(daily_ctx.get('rsi_d'), 0)}",
        f"Volatilité moyenne : {usd(daily_ctx.get('atr_d'))} par jour ({pct(daily_ctx.get('atr_pct'), 1, False)})",
        "",
        "Niveaux clés :",
        f"• Veille : haut {usd(daily_ctx.get('veille_haut'))}, bas {usd(daily_ctx.get('veille_bas'))}, clôture {usd(daily_ctx.get('veille_close'))}",
        f"• 20 jours : haut {usd(daily_ctx.get('haut20'))}, bas {usd(daily_ctx.get('bas20'))}",
        f"• MM50 : {usd(daily_ctx.get('sma50'))} | MM200 : {usd(daily_ctx.get('sma200'))}",
    ]
    if evts:
        lignes += ["", "À surveiller :", *[f"• {e}" for e in evts]]
    if news:
        lignes += ["", "Actus :", *[f"• {n['titre']} ({n['source']})" for n in news[:2]]]
    lignes += ["", f"Biais technique du jour : {_biais(int(tj), prem.get('chg'), prem.get('futures'))}"]
    return f"{cfg.symbol} : avant l'ouverture", "\n".join(lignes), "sunrise", 3


def bilan(cfg: Config, f: pd.DataFrame, trades_jour: list[dict], journal: list[dict]) -> tuple[str, str, str, int]:
    from .engine import stats

    jour = f[f["sess"] == f["sess"].iloc[-1]]
    last = jour.iloc[-1]
    vol_rel = jour["volume"].sum() / last["vol20"] if ok(last.get("vol20")) and last["vol20"] > 0 else np.nan
    lignes = [
        f"Clôture : {usd(last['close'])} ({pct(last['chg_jour'], 2)})",
        f"Plus haut {usd(jour['high'].max())} | plus bas {usd(jour['low'].min())}",
        f"Nasdaq {pct(last.get('mkt_chg'), 2)} | Semi-conducteurs {pct(last.get('sec_chg'), 2)}",
        f"Volume du jour : x{num(vol_rel, 1)} vs moyenne 20 jours",
    ]
    if trades_jour:
        lignes += ["", "Signaux du jour :"]
        motifs = {"T2": "objectif 2", "STOP": "stop", "BE": "sortie à l'entrée après objectif 1",
                  "FIN": "fin de séance", "INVERSE": "signal inverse"}
        for t in trades_jour:
            lignes.append(f"• {SENS[t['sens']].capitalize()}, {nom_setup(t['cle']).lower()} : {_r(t['R'])} "
                          f"({motifs.get(t['motif'], t['motif'])})")
        lignes.append(f"Total du jour : {_r(sum(t['R'] for t in trades_jour))}")
    else:
        lignes += ["", "Aucun signal aujourd'hui. Pas de configuration assez solide."]
    st = stats(journal[-20:])
    if st.get("n", 0) >= 3:
        lignes.append(f"20 derniers signaux : {num(st['gagnants'], 0)} % gagnants, total {_r(st['total'])}")
    return f"{cfg.symbol} : bilan de la séance", "\n".join(lignes), "bar_chart", 3
