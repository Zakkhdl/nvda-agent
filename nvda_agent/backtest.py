"""Backtest : rejoue les ~60 dernières séances avec exactement les règles du suivi en direct.

Deux mesures :
1. « Brut » : toutes les configurations, sans le facteur « historique ».
2. « Walk-forward » : chaque jour, le facteur « historique » n'utilise que les séances passées,
   comme en direct. C'est la mesure honnête de ce que l'agent aurait fait.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as D
from .agent import dates_resultats, evenements
from .config import Config
from .engine import Moteur, rejouer, stats, stats_par_cle
from .features import construire
from .strategy import analyser, choisir_meilleur, nom_setup, points_historique
from .util import num


def _ligne(nom: str, st: dict) -> str:
    if st.get("n", 0) == 0:
        return f"{nom:<38}{0:>6}"
    pf = "inf" if st["pf"] == float("inf") else num(st["pf"], 2)
    return (f"{nom:<38}{st['n']:>6}{num(st['gagnants'], 0) + ' %':>10}{num(st['t1'], 0) + ' %':>9}"
            f"{num(st['esperance'], 2) + ' R':>11}{num(st['total'], 1) + ' R':>10}{pf:>7}{num(st['dd_max'], 1) + ' R':>9}")


def _tableau(titre: str, trades: list[dict]) -> None:
    print(f"\n{titre}")
    print(f"{'Configuration':<38}{'Signaux':>6}{'Gagnants':>10}{'Obj. 1':>9}{'Espérance':>11}{'Total':>10}{'PF':>7}{'DD max':>9}")
    print("-" * 100)
    for cle, st in stats_par_cle(trades).items():
        sens = "Achat" if cle.endswith("_L") else "Vente"
        print(_ligne(f"{sens} : {nom_setup(cle)}", st))
    print("-" * 100)
    print(_ligne("TOTAL", stats(trades)))


def walk_forward(f, evts, res, cfg: Config, base_trades: list[dict], min_seances: int = 15) -> list[dict]:
    """Chaque séance est notée avec un historique calculé uniquement sur les séances précédentes."""
    sess = np.array([str(x)[:10] for x in f["sess"].to_numpy()])
    jours = sorted(set(sess))
    if len(jours) <= min_seances:
        return []
    a = analyser(f, evts, res, None, stop_min_atr=cfg.stop_min_atr)
    for jour in jours[min_seances:]:
        calib = stats_par_cle([t for t in base_trades if t["sess"] < jour])
        m = sess == jour
        for cle, cd in a.cand.items():
            pts = points_historique(calib.get(cle))
            if pts:
                cd["score"][m] = np.clip(cd["score"][m] + pts, 0, 100)
    choisir_meilleur(a)
    mo = Moteur(cfg.seuil, cfg.max_trades_jour, cfg.frais_pct)
    rejouer(a, mo, int(np.searchsorted(sess, jours[min_seances])), len(f))
    return mo.journal


def lancer(cfg: Config, csv: str = "backtest_signaux.csv", marche=None) -> dict:
    mk = marche or D.charger(cfg)
    f = construire(mk)
    evts = evenements(cfg)
    res = dates_resultats(cfg, {}, evts, "") if marche is None else [e["date"] for e in evts if e.get("type") == "RESULTATS"]
    a = analyser(f, evts, res, None, stop_min_atr=cfg.stop_min_atr)
    mo = Moteur(cfg.seuil, cfg.max_trades_jour, cfg.frais_pct)
    rejouer(a, mo, 0, len(f))
    brut = mo.journal
    nb_s = len(set(str(x)[:10] for x in f["sess"].to_numpy()))
    print(f"\nBacktest {cfg.symbol} : {nb_s} séances, du {f.index[0]:%d/%m/%Y} au {f.index[-1]:%d/%m/%Y} ({mk.source})")
    print(f"Seuil {cfg.seuil}/100, {cfg.max_trades_jour} signaux max par jour, frais {num(cfg.frais_pct, 2)} % par aller-retour.")
    print("Gagnants = résultat > 0. Obj. 1 = objectif 1 touché. Espérance = gain moyen par signal en R.")
    print("PF = gains / pertes. DD max = pire série de pertes cumulées. R = distance entrée-stop.")
    _tableau("1) Toutes les configurations (sans filtre historique)", brut)
    wf = walk_forward(f, evts, res, cfg, brut)
    _tableau("2) Walk-forward : filtre historique calculé chaque jour sur le passé seulement", wf)
    if wf:
        debut_wf = min(t["sess"] for t in wf)
        meme = stats([t for t in brut if t["sess"] >= debut_wf])
        print(_ligne(f"Comparaison sans filtre, même période", meme))

    # Sensibilité au seuil
    print("\n3) Sensibilité au seuil de score (sans filtre historique)")
    print(f"{'Seuil':<8}{'Signaux':>8}{'Gagnants':>10}{'Espérance':>11}{'Total':>9}")
    for s in (55, 60, 65, 70, 75, 80):
        m2 = Moteur(s, cfg.max_trades_jour, cfg.frais_pct)
        rejouer(a, m2, 0, len(f))
        st = stats(m2.journal)
        if st.get("n"):
            print(f"{s:<8}{st['n']:>8}{num(st['gagnants'], 0) + ' %':>10}{num(st['esperance'], 2) + ' R':>11}{num(st['total'], 1) + ' R':>9}")
        else:
            print(f"{s:<8}{0:>8}")

    if csv and brut:
        df = pd.DataFrame(brut)
        df["configuration"] = df["cle"].map(nom_setup)
        df["sens"] = df["sens"].map({1: "ACHAT", -1: "VENTE"})
        df.to_csv(csv, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        print(f"\nDétail des {len(df)} signaux : {csv}")
    print("\nÀ lire avec prudence : 60 séances, c'est court, et le passé ne garantit rien.")
    return {"brut": stats(brut), "walk_forward": stats(wf), "trades": brut}
