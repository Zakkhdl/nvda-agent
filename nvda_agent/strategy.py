"""Stratégie : 5 configurations de trading (achat et vente), notées sur 100.

Chaque configuration a son déclencheur, son stop logique et ses objectifs.
La note part de 50 et s'ajuste avec 18 facteurs : tendances jour et 15 min, force de la
tendance (ADX), Nasdaq, semi-conducteurs, force relative, volume relatif à l'heure,
divergences, momentum, extension, place jusqu'au prochain obstacle, taille du stop,
heure, VIX, résultats NVIDIA, annonces macro et historique récent de la configuration.

Les ventes sont calculées en appliquant exactement la même logique au graphique inversé,
ce qui garantit une symétrie parfaite entre achat et vente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SETUPS = {
    "PULLBACK": ("Rebond dans la tendance", "tendance"),
    "ORB": ("Cassure du range d'ouverture", "cassure"),
    "VEILLE": ("Cassure du niveau de la veille", "cassure"),
    "FAUX": ("Faux départ repris", "tendance"),
    "MOYENNE": ("Retour vers la moyenne (VWAP)", "retour"),
}
SENS = {1: "ACHAT", -1: "VENTE"}


def nom_setup(cle: str) -> str:
    base, s = cle.rsplit("_", 1)
    nom = SETUPS[base][0]
    if base == "VEILLE":
        nom = "Cassure du plus haut de la veille" if s == "L" else "Cassure du plus bas de la veille"
    if base == "FAUX":
        nom = "Faux décrochage repris" if s == "L" else "Fausse cassure rejetée"
    return nom


def _shift(a: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype=float)
    out[k:] = a[:-k]
    return out


def _rmin(a: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(a).rolling(n, min_periods=n).min().to_numpy()


def _vue(f: pd.DataFrame, s: int) -> dict:
    """Valeurs vues depuis un acheteur (s=1) ou depuis un vendeur (s=-1, graphique inversé)."""
    g = lambda col: f[col].to_numpy(dtype=float)
    if s == 1:
        v = {
            "o": g("open"), "h": g("high"), "l": g("low"), "c": g("close"),
            "ema21": g("ema21"), "vwap": g("vwap"), "vwap_m2": g("vwap") - 2 * g("vwap_sd"),
            "vwap_p2": g("vwap") + 2 * g("vwap_sd"), "bb_bas": g("bb_lo"), "bb_haut": g("bb_up"),
            "rsi": g("rsi"), "hist": g("macd_hist"),
            "or_haut": g("or_haut"), "or_bas": g("or_bas"), "veille_haut": g("veille_haut"),
            "veille_bas": g("veille_bas"), "seance_haut": g("seance_haut_av"), "haut20": g("haut20"),
            "sma50": g("sma50"), "sma200": g("sma200"), "div": f["div_haussiere"].to_numpy(bool),
        }
    else:
        v = {
            "o": -g("open"), "h": -g("low"), "l": -g("high"), "c": -g("close"),
            "ema21": -g("ema21"), "vwap": -g("vwap"), "vwap_m2": -(g("vwap") + 2 * g("vwap_sd")),
            "vwap_p2": -(g("vwap") - 2 * g("vwap_sd")), "bb_bas": -g("bb_up"), "bb_haut": -g("bb_lo"),
            "rsi": 100 - g("rsi"), "hist": -g("macd_hist"),
            "or_haut": -g("or_bas"), "or_bas": -g("or_haut"), "veille_haut": -g("veille_bas"),
            "veille_bas": -g("veille_haut"), "seance_haut": -g("seance_bas_av"), "haut20": -g("bas20"),
            "sma50": -g("sma50"), "sma200": -g("sma200"), "div": f["div_baissiere"].to_numpy(bool),
        }
    v["or_mil"] = s * g("or_mil")
    v["atr"] = g("atr5")
    for k in ("tendance_jour", "tendance15", "mkt_etat", "sec_etat", "force_rel"):
        v[k] = s * g(k)
    return v


def _premiere_fois(cond: np.ndarray, sess: np.ndarray) -> np.ndarray:
    """Vrai seulement la première fois que la condition est vraie dans la séance."""
    c = pd.Series(cond.astype(int))
    deja = c.groupby(sess).cummax().groupby(sess).shift(1).fillna(0).to_numpy() > 0
    return cond & ~deja


def _setups(f: pd.DataFrame, v: dict) -> dict:
    o, h, l, c, atr = v["o"], v["h"], v["l"], v["c"], v["atr"]
    sl = f["slot"].to_numpy()
    sess = f["sess"].to_numpy()
    ph, pc = _shift(h), _shift(c)
    min_l3 = _rmin(l, 3)
    min_rsi3 = _rmin(v["rsi"], 3)
    haussiere = (c > o) & (c > ph)
    out = {}

    # 1. Rebond dans la tendance : repli sur la moyenne 21 ou le VWAP, puis reprise
    ema21_monte = v["ema21"] > _shift(v["ema21"], 3)
    touche = (min_l3 <= v["ema21"] + 0.15 * atr) | (min_l3 <= v["vwap"] + 0.15 * atr)
    tient = min_l3 >= np.fmin(v["ema21"], v["vwap"]) - 0.6 * atr
    cond = ((sl >= 3) & (sl <= 71) & (v["tendance15"] >= 0) & ema21_monte & touche & tient
            & (c > v["ema21"]) & (c > v["vwap"]) & haussiere & (v["rsi"] >= 40) & (v["rsi"] <= 70))
    out["PULLBACK"] = (cond, min_l3 - 0.15 * atr)

    # 2. Cassure du range d'ouverture (30 premières minutes), première clôture au-delà
    au_dela = np.nan_to_num(c > v["or_haut"], nan=0).astype(bool)
    cond = (sl >= 6) & (sl <= 48) & _premiere_fois(au_dela, sess) & (c > o)
    stop = np.fmin(np.fmax(v["or_mil"], c - 3 * atr), l - 0.1 * atr)
    out["ORB"] = (cond, stop)

    # 3. Cassure du plus haut de la veille (plus bas pour la vente)
    au_dela = np.nan_to_num(c > v["veille_haut"], nan=0).astype(bool)
    cond = (sl >= 3) & (sl <= 66) & _premiere_fois(au_dela, sess) & (c > o)
    stop = np.fmax(np.fmin(l, v["veille_haut"] - 0.5 * atr) - 0.1 * atr, c - 3 * atr)
    out["VEILLE"] = (cond, stop)

    # 4. Faux départ : le plus bas de la veille est enfoncé puis repris avec force
    cond = ((sl >= 3) & (sl <= 69) & (min_l3 < v["veille_bas"] - 0.1 * atr) & (c > v["veille_bas"])
            & (pc <= v["veille_bas"] + 0.25 * atr) & haussiere)
    out["FAUX"] = (cond, min_l3 - 0.15 * atr)

    # 5. Retour vers la moyenne : excès sous la bande VWAP -2 écarts-types, RSI en survente, reprise
    exces = (min_l3 <= v["vwap_m2"]) | (min_l3 <= v["bb_bas"])
    cond = ((sl >= 3) & (sl <= 69) & exces & (min_rsi3 < 30) & haussiere
            & (v["rsi"] > _shift(v["rsi"])) & (c < v["vwap"]))
    out["MOYENNE"] = (cond, min_l3 - 0.2 * atr)
    return out


def _niveau_suivant(v: dict, c: np.ndarray, atr: np.ndarray) -> np.ndarray:
    """Prochain obstacle au-dessus du prix d'entrée (en-dessous pour une vente)."""
    niveaux = np.vstack([v[k] for k in ("veille_haut", "veille_bas", "seance_haut", "or_haut", "or_bas",
                                        "vwap", "vwap_p2", "haut20", "sma50", "sma200", "bb_haut")])
    seuil = c + 0.1 * atr
    niveaux = np.where(niveaux > seuil, niveaux, np.nan)
    with np.errstate(all="ignore"):
        return np.nanmin(np.where(np.isnan(niveaux), np.inf, niveaux), axis=0)


def _evenements(f: pd.DataFrame, evenements: list[dict], resultats: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pénalités et codes liés aux résultats NVIDIA et aux annonces macro."""
    n = len(f)
    sess = pd.DatetimeIndex(f["sess"].to_numpy())
    minute = f["minute"].to_numpy()
    p_res, p_mac = np.zeros(n), np.zeros(n)
    code_res = np.zeros(n, dtype=int)  # 1 = veille, 2 = jour J, 3 = lendemain
    code_mac = np.zeros(n, dtype=int)  # 1 = Fed jour J, 2 = Fed fenêtre, 3 = chiffre macro matin
    jours = pd.DatetimeIndex(sorted({pd.Timestamp(x) for x in resultats if x}))
    if len(jours):
        bd = pd.offsets.BDay()
        for j in jours:
            for delta, pts, code in ((-1, -10, 1), (0, -20, 2), (1, -6, 3)):
                cible = j + delta * bd if delta else j
                m = sess == cible
                p_res[m] = np.minimum(p_res[m], pts)
                code_res[m] = np.where(p_res[m] == pts, code, code_res[m])
    for ev in evenements:
        jour = pd.Timestamp(ev["date"])
        m = sess == jour
        if not m.any():
            continue
        if ev.get("type") == "FOMC":
            fen = m & (minute >= 13 * 60 + 30) & (minute <= 14 * 60 + 45)
            p_mac[m] = np.minimum(p_mac[m], -3)
            code_mac[m] = np.maximum(code_mac[m], 1)
            p_mac[fen] = -15
            code_mac[fen] = 2
        elif ev.get("type") in ("CPI", "EMPLOI"):
            mat = m & (minute < 10 * 60 + 30)
            p_mac[mat] = np.minimum(p_mac[mat], -5)
            code_mac[mat] = np.maximum(code_mac[mat], 3)
    return p_res, code_res, p_mac, code_mac


def points_historique(stats: dict | None) -> int:
    if not stats or stats.get("n", 0) < 12:
        return 0
    e = stats.get("esperance", 0.0)
    if e < -0.15:
        return -12
    if e < 0:
        return -5
    if e > 0.25:
        return 6
    if e > 0.10:
        return 3
    return 0


@dataclass
class Analyse:
    f: pd.DataFrame
    cand: dict = field(default_factory=dict)   # clé -> dict de tableaux
    meilleur: dict = field(default_factory=dict)  # tableaux par bougie : cle, sens, score, stop, t1, t2


# Distance minimale du stop, en ATR 5 min. Validé sur NVDA, AMD, AVGO, TSM et MU (60 séances) :
# en dessous de 2 ATR, le bruit intraday sort la position avant que le mouvement ne démarre.
STOP_MIN_ATR = 2.5


def analyser(f: pd.DataFrame, evenements: list[dict] | None = None, resultats: list[str] | None = None,
             calib: dict | None = None, seuil_conflit: int = 15, stop_min_atr: float | None = None) -> Analyse:
    stop_min_atr = STOP_MIN_ATR if stop_min_atr is None else stop_min_atr
    evenements = evenements or []
    resultats = resultats or []
    calib = calib or {}
    n = len(f)
    sl = f["slot"].to_numpy()
    minute = f["minute"].to_numpy()
    rvol = f["rvol"].to_numpy(dtype=float)
    adx = f["adx15"].to_numpy(dtype=float)
    vix = f["vix"].to_numpy(dtype=float)
    vix_chg = f["vix_chg"].to_numpy(dtype=float)
    p_res, code_res, p_mac, code_mac = _evenements(f, evenements, resultats)

    a = Analyse(f=f)
    for s, suffixe in ((1, "L"), (-1, "S")):
        v = _vue(f, s)
        c, atr = v["c"], v["atr"]
        setups = _setups(f, v)
        prochain = _niveau_suivant(v, c, atr)
        for base, (cond, stop_v) in setups.items():
            famille = SETUPS[base][1]
            cle = f"{base}_{suffixe}"
            stop_v = np.fmin(stop_v, c - stop_min_atr * atr)
            risque = c - stop_v
            valide = cond & np.isfinite(risque) & (risque > 0) & np.isfinite(atr)
            R = np.where(valide, risque, np.nan)
            espace_R = (prochain - c) / R
            t1 = c + R
            t2 = np.where((espace_R >= 1.2) & (espace_R <= 2.5), prochain - 0.05 * atr, c + 2 * R)
            retour = famille == "retour"
            tj, t15 = v["tendance_jour"], v["tendance15"]

            F = {}
            F["tendance_jour"] = np.where(tj > 0, 10, np.where(tj < 0, -8 if retour else -15, 0))
            F["tendance_15m"] = (np.where(t15 > 0, 3, np.where(t15 < 0, -4, 0)) if retour
                                 else np.where(t15 > 0, 8, np.where(t15 < 0, -10, 0)))
            F["adx"] = (np.where(adx < 20, 5, np.where(adx > 30, -10, 0)) if retour
                        else np.where(adx >= 25, 5, np.where(adx < 18, -5, 0)))
            F["marche"] = np.where(v["mkt_etat"] > 0, 8, np.where(v["mkt_etat"] < 0, -10, 0))
            F["secteur"] = np.where(v["sec_etat"] > 0, 5, np.where(v["sec_etat"] < 0, -6, 0))
            F["force_relative"] = np.where(v["force_rel"] > 0.5, 5, np.where(v["force_rel"] < -0.5, -5, 0))
            vol = np.where(rvol >= 2, 8, np.where(rvol >= 1.3, 4, np.where(rvol < 0.7, -8, 0)))
            if famille == "cassure":
                vol = vol + np.where(rvol < 1, -6, 0)
            F["volume"] = vol
            F["divergence"] = np.where(v["div"], 6, 0)
            if not retour:
                hist, phist = v["hist"], _shift(v["hist"])
                F["momentum"] = np.where((hist > 0) & (hist > phist), 4, np.where((hist < 0) & (hist < phist), -3, 0))
                F["extension"] = np.where((c - v["vwap"]) / atr > 4, -8, 0)
                F["rsi_extreme"] = np.where(v["rsi"] > 75, -6, 0)
            F["espace"] = np.where(espace_R < 1, -15, np.where(espace_R >= 2, 5, 0))
            ratio = R / atr
            F["risque"] = np.where(ratio > 3.5, -10, np.where(ratio < 0.6, -5, 0))
            F["horaire"] = (np.where(sl < 3, -10, 0) + np.where((minute >= 12 * 60) & (minute < 13 * 60 + 30), -4, 0)
                            + np.where(minute >= 15 * 60 + 30, -20, 0))
            F["vix"] = np.where(vix >= 30, -5, 0) + np.where(vix_chg >= 8, -6 if s == 1 else 2, 0)
            F["resultats"] = p_res
            F["macro"] = p_mac
            F["historique"] = np.full(n, points_historique(calib.get(cle)))
            brut = 50 + sum(np.nan_to_num(x.astype(float)) for x in F.values())
            score = np.where(valide, np.clip(brut, 0, 100), np.nan)
            a.cand[cle] = {"sens": s, "score": score, "stop": s * stop_v, "t1": s * t1, "t2": s * t2,
                           "entree": s * c, "R": R, "espace_R": espace_R, "obstacle": s * prochain, "facteurs": F}

    a.meilleur = {"code_res": code_res, "code_mac": code_mac}
    choisir_meilleur(a, seuil_conflit)
    return a


def choisir_meilleur(a: Analyse, seuil_conflit: int = 15) -> None:
    """Meilleure configuration par bougie. Si achat et vente sont à moins de 15 points, on s'abstient."""
    cles = list(a.cand)
    n = len(a.f)
    scores = np.vstack([np.nan_to_num(a.cand[k]["score"], nan=-1) for k in cles])
    best = scores.argmax(axis=0)
    best_score = scores[best, np.arange(n)]
    sens = np.array([a.cand[k]["sens"] for k in cles])[best]
    oppose = np.where(sens == 1,
                      scores[[i for i, k in enumerate(cles) if k.endswith("_S")]].max(axis=0),
                      scores[[i for i, k in enumerate(cles) if k.endswith("_L")]].max(axis=0))
    best_score = np.where((oppose >= 0) & (best_score - oppose < seuil_conflit), -1, best_score)
    champs = {}
    for champ in ("stop", "t1", "t2"):
        pile = np.vstack([a.cand[k][champ] for k in cles])
        champs[champ] = pile[best, np.arange(n)]
    a.meilleur.update({"cle": np.array([cles[b] for b in best], dtype=object), "sens": sens,
                       "score": best_score, **champs})


def facteurs(a: Analyse, cle: str, i: int) -> dict:
    return {k: float(v[i]) for k, v in a.cand[cle]["facteurs"].items()}
