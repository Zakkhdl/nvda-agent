"""Une passe de l'agent, lancée toutes les 5 minutes.

Phases (heure de New York) :
- 9h05 à 9h29  : point avant l'ouverture (une fois par jour)
- 9h30 à 15h59 : analyse de chaque nouvelle bougie, signaux, suivi des positions, mouvements brusques
- 16h00 à 16h45 : dernières bougies, clôture des positions, bilan de la séance (une fois par jour)
"""
from __future__ import annotations

import datetime as dt
import json
import time

import numpy as np
import pandas as pd

from . import data as D
from . import messages as M
from .config import NY, Config
from .engine import Moteur, candidat, rejouer, stats_par_cle
from .features import construire
from .notify import envoyer
from .state import charger as charger_etat, sauver as sauver_etat
from .strategy import analyser
from .util import BAR, log, num, ok, pct, usd


def phase(now: pd.Timestamp) -> str:
    if now.weekday() >= 5:
        return "ferme"
    m = now.hour * 60 + now.minute
    if 9 * 60 + 5 <= m < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= m < 16 * 60:
        return "seance"
    if 16 * 60 <= m <= 16 * 60 + 45:
        return "post"
    return "ferme"


def evenements(cfg: Config) -> list[dict]:
    try:
        with open(cfg.events_file, encoding="utf-8") as fh:
            return json.load(fh).get("evenements", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"Calendrier des événements illisible ({cfg.events_file}) : {e}")
        return []


def dates_resultats(cfg: Config, etat: dict, evts: list[dict], aujourdhui: str) -> list[str]:
    cache = etat.setdefault("cache", {})
    if cache.get("res_date") != aujourdhui:
        cache["resultats"] = D.dates_resultats(cfg.symbol)
        cache["res_date"] = aujourdhui
    fichier = [e["date"] for e in evts if e.get("type") == "RESULTATS"]
    return sorted(set(cache.get("resultats", [])) | set(fichier))


def a_surveiller(evts: list[dict], resultats: list[str], jour: pd.Timestamp) -> list[str]:
    out = []
    j = jour.date()
    for e in evts:
        d = dt.date.fromisoformat(e["date"])
        if d == j and e.get("type") != "RESULTATS":
            h, mi = map(int, e.get("heure_ny", "08:30").split(":"))
            paris = pd.Timestamp(dt.datetime.combine(j, dt.time(h, mi)), tz=NY).tz_convert("Europe/Paris")
            out.append(f"{e['titre']} à {paris:%Hh%M} (Paris)")
    prochains = [dt.date.fromisoformat(r) for r in resultats if dt.date.fromisoformat(r) >= j]
    if prochains:
        nb = int(np.busday_count(j, prochains[0]))
        quand = "ce soir" if nb == 0 else "demain soir" if nb == 1 else f"dans {nb} séances ({prochains[0]:%d/%m})"
        if nb <= 10:
            out.append(f"Résultats NVIDIA {quand}, après la clôture")
    return out


def calibrer(cfg: Config, a_base, aujourdhui: str) -> dict:
    """Performance de chaque configuration sur les séances AVANT aujourd'hui (aucune fuite du futur)."""
    sess = np.array([str(x)[:10] for x in a_base.f["sess"].to_numpy()])
    fin = int(np.searchsorted(sess, aujourdhui))
    m = Moteur(cfg.seuil, cfg.max_trades_jour, cfg.frais_pct)
    rejouer(a_base, m, 0, fin)
    return {"date": aujourdhui, "par_setup": stats_par_cle(m.journal), "n": len(m.journal)}


def point_avant_ouverture(cfg: Config, now: pd.Timestamp, etat: dict, dry_run: bool) -> None:
    jour = now.normalize()
    daily, _ = D.bougies(cfg.symbol, cfg, "1d")
    prem = D.premarche(cfg.symbol)
    if prem is None or prem[prem.index >= jour].empty:
        log("Pas de cotation avant-bourse aujourd'hui (jour férié ?). Pas de point d'ouverture.")
        etat["brief_date"] = jour.date().isoformat()
        return
    hier = daily[daily.index < jour]
    dd = hier.copy()
    from . import indicators as ind
    ctx = {
        "veille_close": dd["close"].iloc[-1], "veille_haut": dd["high"].iloc[-1], "veille_bas": dd["low"].iloc[-1],
        "sma50": dd["close"].rolling(50).mean().iloc[-1], "sma200": dd["close"].rolling(200).mean().iloc[-1],
        "rsi_d": ind.rsi(dd["close"]).iloc[-1], "atr_d": ind.atr(dd).iloc[-1],
        "haut20": dd["high"].iloc[-20:].max(), "bas20": dd["low"].iloc[-20:].min(),
    }
    ctx["atr_pct"] = ctx["atr_d"] / ctx["veille_close"] * 100
    pente = dd["close"].rolling(50).mean().diff(10).iloc[-1]
    c, s50, s200 = ctx["veille_close"], ctx["sma50"], ctx["sma200"]
    ctx["tendance_jour"] = 1 if (c > s50 > s200 and pente > 0) else -1 if (c < s50 < s200 and pente < 0) else 0
    p = float(prem[prem.index >= jour]["close"].iloc[-1])
    v = D.vix()
    infos = {"prix": p, "chg": (p / c - 1) * 100, "futures": D.variation_jour("NQ=F"),
             "vix": float(v["close"].iloc[-1]) if v is not None else None}
    evts = evenements(cfg)
    res = dates_resultats(cfg, etat, evts, jour.date().isoformat())
    titre, corps, tag, prio = M.avant_ouverture(cfg, ctx, infos, a_surveiller(evts, res, jour), D.actualites(cfg.symbol))
    envoyer(cfg, titre, corps, tag, prio, dry_run)
    etat["brief_date"] = jour.date().isoformat()


def passe_seance(cfg: Config, now: pd.Timestamp, etat: dict, ph: str, dry_run: bool, marche=None) -> int:
    aujourdhui = now.date().isoformat()
    mk = marche or D.charger(cfg)
    mk.nvda = mk.nvda[mk.nvda.index + BAR <= now]  # uniquement les bougies clôturées
    if len(mk.nvda) < 300:
        raise RuntimeError(f"historique 5 min trop court ({len(mk.nvda)} bougies)")
    f = construire(mk)
    evts = evenements(cfg)
    res = dates_resultats(cfg, etat, evts, aujourdhui)

    # Calibration quotidienne sur les 60 dernières séances (hors aujourd'hui)
    if etat.get("calib", {}).get("date") != aujourdhui:
        t0 = time.time()
        etat["calib"] = calibrer(cfg, analyser(f, evts, res, None, stop_min_atr=cfg.stop_min_atr), aujourdhui)
        log(f"Calibration : {etat['calib']['n']} signaux historiques analysés en {time.time() - t0:.1f} s")
    calib = etat["calib"]["par_setup"]
    a = analyser(f, evts, res, calib, stop_min_atr=cfg.stop_min_atr)

    last = f.iloc[-1]
    ts_last = f.index[-1]
    i_last = len(f) - 1
    m = a.meilleur
    signal_txt = (f"{m['cle'][i_last]} {m['score'][i_last]:.0f}/100" if m["score"][i_last] >= 0 else "aucun")
    log(f"{cfg.symbol} {usd(last['close'])} ({pct(last['chg_jour'], 2)}) bougie {ts_last:%H:%M} NY | "
        f"configuration : {signal_txt} | tendance jour {last['tendance_jour']:+.0f}, "
        f"15 min {num(last['tendance15'], 0)}, ADX {num(last['adx15'], 0)} | Nasdaq {pct(last['mkt_chg'], 2)} | "
        f"VIX {num(last['vix'], 1)} | source {mk.source}")

    # Moteur en direct : on reprend là où la passe précédente s'est arrêtée
    moteur = Moteur(cfg.seuil, cfg.max_trades_jour, cfg.frais_pct)
    moteur.restaurer(etat.get("moteur"))
    dernier = etat.get("last_bar")
    if dernier:
        debut = int(np.searchsorted(f.index, pd.Timestamp(dernier), side="right"))
        debut = max(debut, len(f) - 12)  # pas plus d'une heure de rattrapage
    else:
        debut = len(f) - 1  # premier lancement : pas d'alertes sur le passé
    evs = rejouer(a, moteur, debut, len(f), derniere_est_fin=(ph == "post"))
    nb = 0
    eurusd = None
    for ev in evs:
        retard = (now - (pd.Timestamp(ev["ts"]) + BAR)).total_seconds() / 60
        if ev["type"] == "OUVERTURE":
            if eurusd is None and cfg.capital_eur > 0:
                eurusd = D.dernier_cours("EURUSD=X")
            titre, corps, tag, prio = M.signal(cfg, a, ev["i"], ev["pos"], calib.get(ev["pos"]["cle"]), eurusd)
        else:
            titre, corps, tag, prio = M.suivi(cfg, ev)
        if retard > 12:
            corps += f"\n(Alerte en retard de {retard:.0f} min, données ou serveur lents.)"
        envoyer(cfg, titre, corps, tag, prio, dry_run)
        nb += 1
    journal = etat.setdefault("journal", [])
    journal += [ev["trade"] for ev in evs if "trade" in ev]
    etat["journal"] = journal[-200:]

    # Mouvement brusque (une alerte par heure maximum)
    if ok(last["chg30"]) and abs(last["chg30"]) >= cfg.seuil_mouvement:
        precedent = etat.get("alertes", {}).get("MOUVEMENT")
        if not precedent or ts_last - pd.Timestamp(precedent) >= pd.Timedelta(minutes=60):
            titre, corps, tag, prio = M.mouvement(cfg, last, ts_last, D.actualites(cfg.symbol, 1))
            envoyer(cfg, titre, corps, tag, prio, dry_run)
            etat.setdefault("alertes", {})["MOUVEMENT"] = ts_last.isoformat()
            nb += 1

    # Données figées pendant la séance
    if ph == "seance" and (now - (ts_last + BAR)) > pd.Timedelta(minutes=20) and str(ts_last.date()) == aujourdhui:
        if etat.get("alertes", {}).get("FIGE") != aujourdhui:
            envoyer(cfg, f"Agent {cfg.symbol} : données figées",
                    f"Dernière bougie reçue à {ts_last:%H:%M} (New York). Cotation suspendue ou source en retard.",
                    "warning", 3, dry_run)
            etat.setdefault("alertes", {})["FIGE"] = aujourdhui

    # Bilan de fin de séance
    if ph == "post" and etat.get("recap_date") != aujourdhui and str(ts_last.date()) == aujourdhui:
        if moteur.pos is not None:
            ev = moteur._fermer(ts_last, float(last["close"]), "FIN")
            titre, corps, tag, prio = M.suivi(cfg, ev)
            envoyer(cfg, titre, corps, tag, prio, dry_run)
            etat["journal"].append(ev["trade"])
        trades_jour = [t for t in etat["journal"] if t["sess"] == aujourdhui]
        titre, corps, tag, prio = M.bilan(cfg, f, trades_jour, etat["journal"])
        envoyer(cfg, titre, corps, tag, prio, dry_run)
        etat["recap_date"] = aujourdhui
        nb += 1

    etat["moteur"] = moteur.etat()
    etat["last_bar"] = ts_last.isoformat()
    return nb


def executer(cfg: Config, now: dt.datetime | None = None, force: bool = False, dry_run: bool = False, marche=None) -> int:
    now_ts = pd.Timestamp(now or dt.datetime.now(NY)).tz_convert(NY)
    etat = charger_etat(cfg.state_file)
    nb = 0
    try:
        ph = phase(now_ts)
        if force and ph == "ferme":
            ph = "seance"
        if ph == "ferme":
            log(f"Marché fermé ({now_ts:%a %d/%m %H:%M} New York). Rien à faire.")
            return 0
        if ph == "pre":
            if etat.get("brief_date") != now_ts.date().isoformat():
                point_avant_ouverture(cfg, now_ts, etat, dry_run)
                nb = 1
            else:
                log("Point avant ouverture déjà envoyé.")
        else:
            nb = passe_seance(cfg, now_ts, etat, ph, dry_run, marche)
        if etat.get("erreurs", 0) >= 3:
            envoyer(cfg, f"Agent {cfg.symbol} : rétabli", "Les données arrivent de nouveau.", "white_check_mark", 2, dry_run)
        etat["erreurs"] = 0
    except Exception as e:
        etat["erreurs"] = etat.get("erreurs", 0) + 1
        log(f"Erreur ({etat['erreurs']} d'affilée) : {type(e).__name__} : {e}")
        if etat["erreurs"] == 3:
            envoyer(cfg, f"Agent {cfg.symbol} : problème de données",
                    f"3 échecs d'affilée, plus d'alertes tant que ça dure.\nDernière erreur : {e}", "warning", 3, dry_run)
    finally:
        sauver_etat(cfg.state_file, etat)
    return nb
