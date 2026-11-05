"""Gestion des signaux comme un trader : une position suivie à la fois, stop, objectifs,
stop remonté au prix d'entrée après l'objectif 1, sortie en fin de séance.

Le même moteur sert au backtest et au suivi en direct : ce que mesure le backtest est
exactement ce que l'agent fait en séance.

Règles de calcul du résultat (en R, R = distance entrée-stop) :
- moitié de la position sortie à l'objectif 1 (+1 R), l'autre moitié à l'objectif 2,
  au stop remonté (0 R) ou en fin de séance ;
- si le stop et un objectif sont touchés dans la même bougie, on suppose le pire (stop) ;
- frais et écart achat/vente déduits sur chaque signal.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

LIMITE_OUVERTURE = 71  # pas de nouveau signal après 15h25 New York


@dataclass
class Position:
    cle: str
    sens: int
    entree: float
    stop: float
    stop_initial: float
    t1: float
    t2: float
    risque: float
    ts: str
    sess: str
    score: float
    t1_touche: bool = False


class Moteur:
    def __init__(self, seuil: int, max_jour: int, frais_pct: float, ecart_inverse: int = 10):
        self.seuil = seuil
        self.max_jour = max_jour
        self.frais_pct = frais_pct
        self.ecart_inverse = ecart_inverse
        self.pos: Position | None = None
        self.sess: str | None = None
        self.nb_jour = 0
        self.journal: list[dict] = []

    # --- persistance (suivi en direct) ---
    def etat(self) -> dict:
        return {"pos": asdict(self.pos) if self.pos else None, "sess": self.sess, "nb_jour": self.nb_jour}

    def restaurer(self, e: dict | None) -> None:
        if not e:
            return
        self.pos = Position(**e["pos"]) if e.get("pos") else None
        self.sess = e.get("sess")
        self.nb_jour = int(e.get("nb_jour", 0))

    # --- calculs ---
    def _resultat(self, p: Position, sortie: float) -> float:
        jambe = p.sens * (sortie - p.entree) / p.risque
        r = 0.5 * 1.0 + 0.5 * jambe if p.t1_touche else jambe
        return r - (self.frais_pct / 100) * p.entree / p.risque

    def _fermer(self, ts, prix: float, motif: str) -> dict:
        p = self.pos
        res = self._resultat(p, prix)
        trade = {"cle": p.cle, "sens": p.sens, "ouverture": p.ts, "fermeture": str(ts), "sess": p.sess,
                 "entree": p.entree, "stop_initial": p.stop_initial, "t1": p.t1, "t2": p.t2,
                 "sortie": prix, "motif": motif, "R": round(res, 3), "score": p.score, "t1_touche": p.t1_touche}
        self.journal.append(trade)
        self.pos = None
        return {"type": motif, "ts": str(ts), "prix": prix, "trade": trade}

    def pas(self, i: int, ts, sess: str, slot: int, o: float, h: float, l: float, c: float,
            fin_seance: bool, cand: dict | None) -> list[dict]:
        """Traite la bougie i (clôturée). cand = meilleur signal sur cette bougie ou None."""
        ev: list[dict] = []
        if sess != self.sess:
            if self.pos is not None:  # séance écourtée : sortie au dernier cours connu
                ev.append(self._fermer(ts, o, "FIN"))
            self.sess, self.nb_jour = sess, 0

        p = self.pos
        if p is not None and p.ts != str(ts):
            s = p.sens
            defavorable = l if s == 1 else h
            favorable = h if s == 1 else l
            if s * (defavorable - p.stop) <= 0:
                prix = p.stop if s * (o - p.stop) > 0 else o  # ouverture au-delà du stop : sortie à l'ouverture
                ev.append(self._fermer(ts, prix, "BE" if p.t1_touche else "STOP"))
            else:
                if not p.t1_touche and s * (favorable - p.t1) >= 0:
                    p.t1_touche = True
                    p.stop = p.entree
                    ev.append({"type": "T1", "ts": str(ts), "prix": p.t1, "pos": asdict(p)})
                if self.pos is not None and p.t1_touche and s * (favorable - p.t2) >= 0:
                    ev.append(self._fermer(ts, p.t2, "T2"))
            if self.pos is not None and fin_seance:
                ev.append(self._fermer(ts, c, "FIN"))

        if cand is not None and cand["score"] >= self.seuil and slot <= LIMITE_OUVERTURE and not fin_seance:
            if self.pos is not None and self.pos.sens != cand["sens"] and cand["score"] >= self.seuil + self.ecart_inverse:
                ev.append(self._fermer(ts, c, "INVERSE"))
            if self.pos is None and self.nb_jour < self.max_jour:
                self.pos = Position(cle=cand["cle"], sens=int(cand["sens"]), entree=c, stop=cand["stop"],
                                    stop_initial=cand["stop"], t1=cand["t1"], t2=cand["t2"],
                                    risque=abs(c - cand["stop"]), ts=str(ts), sess=sess, score=float(cand["score"]))
                self.nb_jour += 1
                ev.append({"type": "OUVERTURE", "ts": str(ts), "prix": c, "pos": asdict(self.pos), "i": i})
        return ev


def candidat(a, i: int) -> dict | None:
    m = a.meilleur
    if m["score"][i] < 0 or not np.isfinite(m["stop"][i]):
        return None
    return {"cle": m["cle"][i], "sens": int(m["sens"][i]), "score": float(m["score"][i]),
            "stop": float(m["stop"][i]), "t1": float(m["t1"][i]), "t2": float(m["t2"][i])}


def fin_de_seance(f: pd.DataFrame) -> np.ndarray:
    sess = f["sess"].to_numpy()
    suivant_diff = np.r_[sess[1:] != sess[:-1], True]
    return (f["slot"].to_numpy() >= 77) | suivant_diff


def rejouer(a, moteur: Moteur, debut: int = 0, fin: int | None = None, derniere_est_fin: bool = True) -> list[dict]:
    """Fait passer les bougies [debut, fin) dans le moteur. Renvoie tous les événements."""
    f = a.f
    fin = len(f) if fin is None else fin
    fds = fin_de_seance(f)
    if not derniere_est_fin and fin == len(f):
        fds = fds.copy()
        fds[-1] = f["slot"].to_numpy()[-1] >= 77
    o, h, l, c = (f[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    sl = f["slot"].to_numpy()
    sess = [str(x)[:10] for x in f["sess"].to_numpy()]
    idx = f.index
    ev = []
    for i in range(debut, fin):
        ev += moteur.pas(i, idx[i], sess[i], int(sl[i]), o[i], h[i], l[i], c[i], bool(fds[i]), candidat(a, i))
    return ev


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    r = np.array([t["R"] for t in trades], dtype=float)
    gains, pertes = r[r > 0].sum(), -r[r < 0].sum()
    courbe = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, courbe]) - np.r_[0, courbe]).max())
    return {"n": int(len(r)), "gagnants": float((r > 0).mean() * 100), "esperance": float(r.mean()),
            "total": float(r.sum()), "pf": float(gains / pertes) if pertes > 0 else float("inf"),
            "dd_max": dd, "t1": float(np.mean([t["t1_touche"] for t in trades]) * 100)}


def stats_par_cle(trades: list[dict]) -> dict:
    out = {}
    for cle in sorted({t["cle"] for t in trades}):
        out[cle] = stats([t for t in trades if t["cle"] == cle])
    return out
