"""Passage du soir, après la clôture de Wall Street.

1. Télécharge l'historique journalier de toutes les valeurs (depuis 2004).
2. Calcule les signaux et rejoue 20 ans pour donner l'historique de chaque type de signal.
3. Fait avancer le portefeuille modèle d'une séance : exécutions du jour, stops, objectifs, stop suiveur.
4. Envoie uniquement ce qu'il y a à faire : achats pour demain, stops à remonter, ventes, résultats à venir.
5. Le vendredi : bilan de la semaine.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from . import data as D
from . import messages as M
from .config import NY, Config
from .notify import envoyer
from .portfolio import Portefeuille, stats
from .simulation import Rejoueur, preparer_tout, simuler
from .state import charger as charger_etat, sauver as sauver_etat
from .util import jour, log, pct, usd

CLOTURE_OK = dt.time(16, 15)  # la bougie du jour est considérée définitive après 16h15 New York


def evenements(cfg: Config) -> list[dict]:
    try:
        with open(cfg.events_file, encoding="utf-8") as fh:
            return json.load(fh).get("evenements", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def resultats_cache(cfg: Config, etat: dict, aujourdhui: str) -> dict:
    cache = etat.setdefault("cache", {})
    if cache.get("res_date") != aujourdhui:
        res = {s: D.dates_resultats(s) for s in cfg.valeurs}
        anciens = cache.get("resultats", {})
        cache["resultats"] = {s: (v or anciens.get(s, [])) for s, v in res.items()}
        cache["res_date"] = aujourdhui
    fichier = [e["date"] for e in evenements(cfg) if e.get("type") == "RESULTATS"]
    out = dict(cache.get("resultats", {}))
    if "NVDA" in out or "NVDA" in cfg.valeurs:
        out["NVDA"] = sorted(set(out.get("NVDA", [])) | set(fichier))
    return out


def mouvement_resultats(df: pd.DataFrame, dates: list[str], n: int = 4) -> float | None:
    """Mouvement moyen (en %) autour des dernières publications de résultats."""
    passes = [pd.Timestamp(x) for x in dates if pd.Timestamp(x) < df.index[-1]][-n:]
    mv = []
    for d in passes:
        i = df.index.searchsorted(d)
        if 1 <= i < len(df) - 1:
            c = df["close"].to_numpy()
            mv.append(max(abs(c[i] / c[i - 1] - 1), abs(c[i + 1] / c[i] - 1)) * 100)
    return float(np.mean(mv)) if mv else None


def a_venir(cfg: Config, date: pd.Timestamp, resultats: dict) -> list[str]:
    fin = date + pd.Timedelta(days=15)
    out = []
    for s, ds in resultats.items():
        for x in ds:
            t = pd.Timestamp(x)
            if date < t <= fin:
                out.append((t, f"{jour(t)} : résultats {s}"))
    for e in evenements(cfg):
        t = pd.Timestamp(e["date"])
        if date < t <= fin and e.get("type") in ("FOMC", "CPI", "EMPLOI"):
            out.append((t, f"{jour(t)} : {e['titre']}"))
    return [x for _, x in sorted(out)]


def executer(cfg: Config, now: dt.datetime | None = None, force: bool = False, dry_run: bool = False,
             donnees: dict | None = None) -> int:
    now_ts = pd.Timestamp(now or dt.datetime.now(NY)).tz_convert(NY)
    etat = charger_etat(cfg.state_file)
    nb = 0
    try:
        if now_ts.weekday() >= 5 and not force:
            log("Week-end : rien à faire.")
            return 0
        symboles = list(dict.fromkeys(list(cfg.valeurs) + [cfg.marche, cfg.secteur]))
        don = donnees if donnees is not None else D.historique(symboles, debut="2004-01-01")
        aujourdhui = pd.Timestamp(now_ts.date())
        if now_ts.time() < CLOTURE_OK:  # séance en cours : on ignore la bougie incomplète du jour
            don = {s: d[d.index < aujourdhui] for s, d in don.items()}
        derniere = max(d.index[-1] for s, d in don.items() if s in cfg.valeurs)
        date_txt = str(derniere.date())
        if etat.get("derniere_date") == date_txt and not force:
            log(f"Séance du {date_txt} déjà analysée.")
            return 0

        resultats = resultats_cache(cfg, etat, str(now_ts.date()))
        evalues = preparer_tout(don, cfg, resultats)

        # Historique de chaque type de signal sur 20 ans (backtest complet, recalculé chaque soir)
        pf_hist, _, _ = simuler(evalues, cfg, debut="2006-01-01")
        par_setup = {k: stats([t for t in pf_hist.journal if t["setup"] == k]) for k in ("REPLI", "CASSURE", "REPRISE")}
        par_valeur = {}
        for t in pf_hist.journal:
            par_valeur.setdefault(f"{t['symbole']}_{t['setup']}", []).append(t)
        par_valeur = {k: stats(v) for k, v in par_valeur.items()}

        # Portefeuille modèle en direct
        pf = Portefeuille(cfg)
        pf.restaurer(etat.get("portefeuille"))
        rj = Rejoueur(evalues)
        precedente = etat.get("derniere_date")
        a_traiter = [d for d in rj.dates if precedente is None or d > pd.Timestamp(precedente)]
        a_traiter = a_traiter[-1:] if precedente is None else a_traiter[-5:]
        eur = D.eurusd() if cfg.capital_eur > 0 else None
        journal = etat.setdefault("journal", [])
        for d in a_traiter:
            evs = pf.jour(str(d)[:10], rj.barres(d), rj.signaux(d, cfg.seuil))
            for ev in evs:
                s = ev["symbole"]
                t = ev["type"]
                if t == "SIGNAL":
                    row = evalues[s].iloc[ev["signal"]["i"]]
                    msg = M.signal(cfg, ev, row, par_setup.get(ev["ordre"]["setup"]),
                                   par_valeur.get(f"{s}_{ev['ordre']['setup']}"), eur)
                elif t == "ACHAT":
                    msg = M.achat(cfg, ev)
                elif t == "ANNULE":
                    msg = M.annule(cfg, ev)
                elif t == "T1":
                    msg = M.t1(cfg, ev)
                elif t == "STOP_MONTE":
                    msg = M.stop_monte(cfg, ev)
                elif t == "SORTIE":
                    msg = M.sortie(cfg, ev)
                    journal.append(ev["trade"])
                elif t == "SORTIE_PREVUE":
                    msg = M.sortie_prevue(cfg, ev)
                elif t == "RESULTATS":
                    msg = M.resultats(cfg, ev, mouvement_resultats(don[s], resultats.get(s, [])))
                else:
                    continue
                titre, corps, tag, prio = msg
                envoyer(cfg, titre, corps, tag, prio, dry_run, lien=cfg.lien(s))
                nb += 1

        # Résumé dans le journal d'exécution
        candidats = [(s, d.iloc[-1]) for s, d in evalues.items()]
        log(f"Séance du {date_txt} analysée. Positions : {', '.join(pf.positions) or 'aucune'}. "
            f"Ordres pour demain : {', '.join(pf.ordres) or 'aucun'}.")
        for s, row in candidats:
            log(f"  {s:<6} {usd(row['close'])} {pct(row['perf_jour'], 1):>8} | configuration : "
                f"{row['setup'] or '-'} {int(row['score']) if row['setup'] else ''}")

        # Bilan du vendredi
        if derniere.weekday() == 4 and etat.get("hebdo") != date_txt:
            titre, corps, tag, prio = M.hebdo(cfg, date_txt, evalues, {k: v for k, v in pf.etat()["positions"].items()},
                                              journal, {}, a_venir(cfg, derniere, resultats), don.get(cfg.marche))
            envoyer(cfg, titre, corps, tag, prio, dry_run)
            etat["hebdo"] = date_txt
            nb += 1

        etat["portefeuille"] = pf.etat()
        etat["journal"] = journal[-300:]
        etat["derniere_date"] = date_txt
        if etat.get("erreurs", 0) >= 2:
            envoyer(cfg, "Agent : rétabli", "Les données arrivent de nouveau.", "white_check_mark", 2, dry_run)
        etat["erreurs"] = 0
    except Exception as e:
        etat["erreurs"] = etat.get("erreurs", 0) + 1
        log(f"Erreur ({etat['erreurs']} d'affilée) : {type(e).__name__} : {e}")
        if etat["erreurs"] == 2:
            envoyer(cfg, "Agent : problème de données",
                    f"2 échecs d'affilée. Pas d'analyse ce soir.\nErreur : {e}", "warning", 3, dry_run)
    finally:
        if not dry_run:  # un aperçu ne modifie jamais la mémoire de l'agent
            sauver_etat(cfg.state_file, etat)
    return nb
