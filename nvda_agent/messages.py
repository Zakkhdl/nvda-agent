"""Rédaction des alertes, courtes et actionnables sur iPhone."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import Config
from .data import nom
from .strategy import SETUPS
from .util import jour, num, ok, pct, r, usd

AVERTISSEMENT = "Signal technique, pas un conseil."
MOTIFS = {"STOP": "stop touché", "BE": "sortie au prix d'entrée", "SUIVEUR": "stop suiveur touché",
          "DUREE": "durée maximale atteinte"}


def _taille(cfg: Config, prix: float, stop: float, eurusd: float | None) -> str | None:
    if cfg.capital_eur <= 0 or not ok(eurusd) or prix <= stop:
        return None
    cap_usd = cfg.capital_eur * eurusd
    n = math.floor(min(cap_usd * cfg.risque_pct / 100 / (prix - stop), cap_usd * cfg.poids_max_pct / 100 / prix))
    if n <= 0:
        return "Taille : capital trop faible pour ce stop."
    return (f"Taille : {n} actions ≈ {num(n * prix / eurusd, 0)} € "
            f"(perte au stop ≈ {num(n * (prix - stop) / eurusd, 0)} €)")


def _raisons(row: pd.Series, symbole: str) -> tuple[list[str], list[str]]:
    pour, contre = [], []

    def ajoute(col, txt_pour, txt_contre=None):
        v = row.get(col, 0)
        if v > 0 and txt_pour:
            pour.append(txt_pour)
        elif v < 0 and txt_contre:
            contre.append(txt_contre)

    ajoute("f_marche", "Nasdaq en tendance haussière", "Nasdaq sous sa moyenne 200 jours (marché baissier)")
    ajoute("f_secteur", "Semi-conducteurs en tendance haussière", "Semi-conducteurs en tendance baissière")
    ajoute("f_force_relative", f"Plus forte que le Nasdaq sur 6 mois ({pct(row.get('rs126'), 0)})",
           f"Plus faible que le Nasdaq sur 6 mois ({pct(row.get('rs126'), 0)})")
    ajoute("f_tendance_longue", "Au-dessus de sa moyenne 30 semaines, qui monte", "Sous sa moyenne 30 semaines")
    ajoute("f_adx", f"Tendance forte (ADX {num(row.get('adx'), 0)})")
    ajoute("f_sommet", f"Proche de son plus haut annuel ({pct(row.get('dist_haut52', 0) * 100, 0)})",
           f"Loin de son plus haut annuel ({pct(row.get('dist_haut52', 0) * 100, 0)})")
    ajoute("f_volume", f"Volume x{num(row.get('vol_rel'), 1)} vs moyenne", f"Volume faible (x{num(row.get('vol_rel'), 1)})")
    ajoute("f_extension", "", "Déjà très au-dessus de sa moyenne 50 jours")
    ajoute("f_rsi", "", f"RSI élevé ({num(row.get('rsi'), 0)})")
    ajoute("f_risque", "", "Stop large (plus de 12 %)")
    if row.get("setup") == "CASSURE":
        contre.append("Cassures moins fiables que les replis sur 20 ans")
        base = row.get("f_base", 0) + 8
        if base > 0:
            pour.append("Base de consolidation serrée")
        elif base < 0:
            contre.append("Base de consolidation large")
    nb = row.get("seances_resultats", np.inf)
    if ok(nb) and nb <= 10:
        contre.append(f"Résultats dans {int(nb)} séances")
    return pour, contre


def _hist(stats_setup: dict | None, stats_valeur: dict | None) -> list[str]:
    out = []
    if stats_valeur and stats_valeur.get("n", 0) >= 5:
        out.append(f"Sur cette valeur depuis 2006 : {stats_valeur['n']} cas, {num(stats_valeur['gagnants'], 0)} % gagnants, "
                   f"moyenne {r(stats_valeur['esperance'])}")
    if stats_setup and stats_setup.get("n", 0) >= 10:
        out.append(f"Toutes valeurs : {stats_setup['n']} cas, {num(stats_setup['gagnants'], 0)} % gagnants, "
                   f"moyenne {r(stats_setup['esperance'])}, durée {num(stats_setup['jours'], 0)} séances")
    return out


def signal(cfg: Config, ev: dict, row: pd.Series, stats_setup, stats_valeur, eurusd) -> tuple[str, str, str, int]:
    o, s = ev["ordre"], ev["symbole"]
    note = "A" if o["score"] >= cfg.seuil_a else "B"
    prix, stop = o["prix_signal"], o["stop"]
    risque = prix - stop
    t1 = prix + cfg.objectif_r * risque
    titre = f"ACHAT {s} ({nom(s)}) {note} {int(o['score'])}/100"
    lignes = [
        f"{SETUPS[o['setup']]}",
        f"Clôture : {usd(prix)} ({pct(row.get('perf_jour'), 1)})",
        "",
        "Ordre pour demain :",
        "• Achat à l'ouverture (15h30)",
        f"• Annule si l'ouverture dépasse {usd(o['max_ouverture'])}",
        f"• Stop à poser tout de suite : {usd(stop)} ({pct(-risque / prix * 100, 1)})",
        f"• Objectif 1 : {usd(t1)} ({pct(cfg.objectif_r * risque / prix * 100, 1)}) : vends la moitié",
        "• Ensuite : stop suiveur, je te dis quand le remonter",
        f"• Durée maximale : {cfg.duree_max // 5} semaines",
    ]
    t = _taille(cfg, prix, stop, eurusd)
    if t:
        lignes.append(t)
    pour, contre = _raisons(row, s)
    if pour:
        lignes += ["", "Pour :", *[f"• {p}" for p in pour[:6]]]
    if contre:
        lignes += ["Contre :", *[f"• {c}" for c in contre[:4]]]
    h = _hist(stats_setup, stats_valeur)
    if h:
        lignes += ["", "Historique :", *[f"• {x}" for x in h]]
    lignes.append(AVERTISSEMENT)
    return titre, "\n".join(lignes), "green_circle", 5 if note == "A" else 4


def achat(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    p = ev["pos"]
    return (f"{p['symbole']} acheté à {usd(p['entree'])}",
            f"Exécution à l'ouverture du {jour(ev['date'])} (portefeuille modèle).\n"
            f"Stop : {usd(p['stop'])} | Objectif 1 recalculé : {usd(p['t1'])}\n"
            "Si ton prix d'achat diffère, garde le même stop.", "white_check_mark", 3)


def annule(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    return (f"{ev['symbole']} : achat annulé",
            f"Ouverture à {usd(ev['ouverture'])} : {ev['motif']}. N'achète pas. Si c'est déjà fait, garde le stop à "
            f"{usd(ev['ordre']['stop'])}.", "no_entry", 3)


def t1(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    p = ev["pos"]
    return (f"{p['symbole']} : objectif 1 atteint ({usd(ev['prix'])})",
            f"Vends la moitié de ta position si ce n'est pas déjà fait.\n"
            f"Remonte le stop au prix d'entrée : {usd(p['stop'])}.\n"
            f"Le reste suit le stop suiveur.", "dart", 5)


def stop_monte(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    p = ev["pos"]
    gain = (p["stop"] - p["entree"]) / p["risque"]
    return (f"{p['symbole']} : remonte ton stop à {usd(p['stop'])}",
            f"Ancien stop : {usd(ev['ancien'])}. Gain verrouillé : {r(gain)} sur le reste de la position.",
            "arrow_up", 3)


def sortie(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    t = ev["trade"]
    titre = f"{t['symbole']} : {MOTIFS.get(t['motif'], t['motif'])} ({r(t['R'])})"
    corps = (f"Sortie à {usd(t['sortie'])} le {jour(ev['date'])}. Entrée {usd(t['entree'])} le {jour(t['date_entree'])}.\n"
             f"Résultat : {r(t['R'])}, soit {pct(t['rendement_pct'], 1)} sur le capital engagé ({t['jours']} séances).")
    if t["motif"] in ("STOP", "BE", "SUIVEUR"):
        corps += "\nSi ton ordre stop était en place, il a été exécuté."
    return titre, corps, "x" if t["R"] < 0 else "trophy", 5


def sortie_prevue(cfg: Config, ev: dict) -> tuple[str, str, str, int]:
    p = ev["pos"]
    gain = (ev["cours"] - p["entree"]) / p["risque"]
    return (f"{p['symbole']} : vends demain à l'ouverture",
            f"{cfg.duree_max // 5} semaines écoulées. Cours {usd(ev['cours'])}, environ {r(gain)} sur la position.",
            "bell", 5)


def resultats(cfg: Config, ev: dict, mouvement: float | None) -> tuple[str, str, str, int]:
    p = ev["pos"]
    gain = (ev["cours"] - p["entree"]) / p["risque"]
    quand = "ce soir ou demain" if ev["seances"] <= 1 else f"dans {ev['seances']} séances"
    lignes = [f"Résultats {quand}. Ta position : {r(gain)}."]
    if ok(mouvement):
        lignes.append(f"Mouvement moyen le jour des résultats : ±{num(mouvement, 1)} %.")
    lignes.append("Le stop ne protège pas d'un écart à l'ouverture. Option prudente : alléger si tu es peu ou pas en gain.")
    return f"{p['symbole']} : résultats à venir", "\n".join(lignes), "warning", 4


def hebdo(cfg: Config, date: str, evalues: dict, positions: dict, journal: list, stats_all: dict,
          a_venir: list[str], marche: pd.DataFrame | None) -> tuple[str, str, str, int]:
    from .portfolio import stats

    lignes = []
    if marche is not None and len(marche) > 205:
        c = marche["close"]
        m200 = c.rolling(200).mean().iloc[-1]
        etat = "haussier" if c.iloc[-1] > m200 else "baissier (sous la MM200)"
        lignes.append(f"Nasdaq : {pct((c.iloc[-1] / c.iloc[-6] - 1) * 100, 1)} sur la semaine, régime {etat}")
    lignes += ["", "Positions :"]
    if positions:
        for s, p in positions.items():
            cours = float(evalues[s]["close"].iloc[-1]) if s in evalues else p["entree"]
            lignes.append(f"• {s} : {usd(cours)} ({r((cours - p['entree']) / p['risque'])}), stop {usd(p['stop'])}")
    else:
        lignes.append("• Aucune")
    classement = sorted(((s, float(d["rs126"].iloc[-1]), d.iloc[-1]) for s, d in evalues.items()
                         if ok(d["rs126"].iloc[-1])), key=lambda x: -x[1])
    lignes += ["", "Force relative 6 mois vs Nasdaq :"]
    for s, rs, row in classement[:5]:
        tend = "tendance OK" if row["close"] > row["sma200"] and row["sma50"] > row["sma200"] else "hors tendance"
        lignes.append(f"• {s} {pct(rs, 0)} ({tend})")
    if a_venir:
        lignes += ["", "À venir :", *[f"• {x}" for x in a_venir[:6]]]
    st = stats(journal)
    if st.get("n", 0):
        lignes += ["", f"Signaux clôturés depuis le début : {st['n']}, {num(st['gagnants'], 0)} % gagnants, total {r(st['total'])}"]
    return f"Bilan de la semaine du {jour(date)}", "\n".join(lignes), "bar_chart", 3
