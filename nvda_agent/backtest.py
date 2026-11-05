"""Backtest du portefeuille sur 20 ans, avec les règles exactes du suivi réel.

Affiche :
1. La performance du portefeuille comparée au Nasdaq (QQQ) et à l'achat-conservation des valeurs suivies.
2. Les statistiques des signaux : par configuration, par valeur, par période.
3. Un contrôle sur 15 autres valeurs (dont des perdantes) pour mesurer le biais du survivant.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from . import data as D
from .agent import CLOTURE_OK, resultats_cache
from .config import NY
from .config import Config
from .portfolio import stats
from .simulation import performances, preparer_tout, simuler
from .strategy import SETUPS
from .util import num

CONTROLE = ["AAPL", "INTC", "CSCO", "IBM", "QCOM", "TXN", "ORCL", "ADBE", "CRM", "NFLX", "JPM", "XOM", "KO", "PFE", "GE"]


def _l(nom: str, st: dict) -> str:
    if not st.get("n"):
        return f"{nom:<34}{0:>6}"
    pf = "inf" if st["pf"] == float("inf") else num(st["pf"], 2)
    return (f"{nom:<34}{st['n']:>6}{num(st['gagnants'], 0) + ' %':>10}{num(st['esperance'], 2) + ' R':>10}"
            f"{pf:>7}{num(st['rendement_moyen'], 1) + ' %':>10}{num(st['jours'], 0):>8}")


def _p(nom: str, p: dict, expo: float | None = None) -> str:
    e = f"{num(expo, 0)} %" if expo is not None else "100 %"
    return (f"{nom:<34}{num(p['cagr'], 1) + ' %':>10}{num(p['dd_max'], 1) + ' %':>12}{num(p['sharpe'], 2):>8}"
            f"{num(p['total'], 0) + ' %':>12}{e:>10}")


def equi_pondere(don: dict, valeurs, debut) -> pd.Series:
    px = pd.DataFrame({s: don[s]["close"] for s in valeurs if s in don})
    rets = px / px.shift(1) - 1
    rets = rets[rets.index >= pd.Timestamp(debut)]
    return (1 + rets.mean(axis=1, skipna=True).fillna(0)).cumprod() * 100


def lancer(cfg: Config, debut: str = "2006-01-01", csv: str = "backtest_trades.csv", donnees: dict | None = None,
           controle: bool = True) -> dict:
    symboles = list(dict.fromkeys(list(cfg.valeurs) + [cfg.marche, cfg.secteur]))
    don = donnees or D.historique(symboles, debut="2004-01-01")
    if donnees is None:
        maintenant = pd.Timestamp.now(tz=NY)
        if maintenant.time() < CLOTURE_OK:  # séance en cours : bougie du jour incomplète
            don = {s: d[d.index < pd.Timestamp(maintenant.date())] for s, d in don.items()}
    res = resultats_cache(cfg, {}, "backtest") if donnees is None else {}
    ev = preparer_tout(don, cfg, res)
    pf, courbe, investi = simuler(ev, cfg, debut=debut)
    T = pf.journal

    print(f"\nBACKTEST du {courbe.index[0]:%d/%m/%Y} au {courbe.index[-1]:%d/%m/%Y} : {', '.join(ev)}")
    print(f"Risque {num(cfg.risque_pct, 1)} % par position, {cfg.max_positions} positions max, frais {num(cfg.frais_pct, 2)} % par ordre.")
    print(f"\n{'Portefeuille':<34}{'Par an':>10}{'Pire baisse':>12}{'Sharpe':>8}{'Total':>12}{'Investi':>10}")
    print("-" * 84)
    print(_p("Stratégie", performances(courbe), investi.mean() * 100))
    if cfg.marche in don:
        q = don[cfg.marche]["close"]
        print(_p("Nasdaq 100 (QQQ) conservé", performances(q[q.index >= courbe.index[0]])))
    print(_p("Valeurs suivies, à parts égales", performances(equi_pondere(don, cfg.valeurs, courbe.index[0]))))

    print(f"\n{'Signaux':<34}{'Nombre':>6}{'Gagnants':>10}{'Moyenne':>10}{'PF':>7}{'Rdt moy.':>10}{'Séances':>8}")
    print("-" * 85)
    for k in SETUPS:
        print(_l(SETUPS[k], stats([t for t in T if t["setup"] == k])))
    print(_l("TOTAL", stats(T)))
    print(_l("  2006 à 2015", stats([t for t in T if t["date_entree"] < "2016"])))
    print(_l("  2016 à aujourd'hui", stats([t for t in T if t["date_entree"] >= "2016"])))
    print()
    for s in ev:
        print(_l(f"  {s}", stats([t for t in T if t["symbole"] == s])))

    if controle and donnees is None:
        cfg2 = dataclasses.replace(cfg, valeurs=tuple(CONTROLE))
        don2 = D.historique(CONTROLE + [cfg.marche, cfg.secteur], debut="2004-01-01")
        ev2 = preparer_tout(don2, cfg2)
        pf2, c2, i2 = simuler(ev2, cfg2, debut=debut)
        print(f"\nCONTRÔLE sur 15 autres valeurs (dont Intel, Cisco, IBM, General Electric, Pfizer)")
        print(_l("Signaux", stats(pf2.journal)))
        print(_p("Portefeuille", performances(c2), i2.mean() * 100))
        print(_p("Ces 15 valeurs, à parts égales", performances(equi_pondere(don2, CONTROLE, c2.index[0]))))

    if csv and T:
        df = pd.DataFrame(T)
        df["configuration"] = df["setup"].map(SETUPS)
        df.to_csv(csv, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        print(f"\nDétail des {len(df)} signaux : {csv}")
    print("\nR = distance entrée-stop. Moyenne = gain moyen par signal, frais inclus.")
    print("Attention : la liste suivie est choisie aujourd'hui, avec des valeurs qui ont beaucoup monté (biais du survivant).")
    print("Le contrôle sur d'autres valeurs donne une idée plus prudente. Le passé ne garantit rien.")
    return {"stats": stats(T), "perf": performances(courbe), "trades": T}
