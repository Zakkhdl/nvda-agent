"""Portefeuille modèle : exactement les règles que l'agent te demande d'appliquer.

Chaque soir (jour J, après la clôture) :
1. Les ventes prévues et les achats décidés la veille s'exécutent à l'ouverture de J.
   Un achat est annulé si l'ouverture dépasse la clôture de la veille + 1 volatilité (pas de poursuite)
   ou si elle est déjà sous le stop.
2. Pour chaque position : stop touché (sortie au stop, ou à l'ouverture si elle est en dessous),
   sinon objectif 1 touché (vente de la moitié, stop remonté au prix d'entrée).
   Le stop suiveur suit la plus haute clôture moins 3 volatilités et ne redescend jamais.
   Après 40 séances, sortie le lendemain à l'ouverture.
3. Nouveaux signaux : ordres d'achat pour l'ouverture de J+1, les meilleures notes d'abord.

Taille : le stop fait perdre 1 % du capital (réglable), avec 25 % du capital au plus par valeur.
Frais : un pourcentage du montant de chaque ordre, achat comme vente.
Si stop et objectif sont touchés le même jour, on suppose le pire : le stop.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .config import Config


@dataclass
class Position:
    symbole: str
    setup: str
    score: float
    date_signal: str
    date_entree: str
    entree: float
    stop: float
    stop_initial: float
    t1: float
    quantite: float
    quantite_init: float
    risque: float               # par action
    plus_haut: float
    cout: float                 # montant payé, frais inclus
    encaisse: float = 0.0       # montant encaissé par les ventes, frais déduits
    t1_touche: bool = False
    jours: int = 0
    sortie_prevue: str = ""
    alerte_resultats: bool = False


@dataclass
class Ordre:
    symbole: str
    setup: str
    score: float
    date_signal: str
    prix_signal: float
    stop: float
    max_ouverture: float


@dataclass
class Portefeuille:
    cfg: Config
    capital: float = 100_000.0
    cash: float = field(init=False)
    positions: dict = field(default_factory=dict)
    ordres: dict = field(default_factory=dict)
    journal: list = field(default_factory=list)
    derniers_cours: dict = field(default_factory=dict)

    def __post_init__(self):
        self.cash = self.capital

    # ------------------------------------------------------------------ état
    def etat(self) -> dict:
        return {"capital": self.capital, "cash": self.cash,
                "positions": {k: asdict(v) for k, v in self.positions.items()},
                "ordres": {k: asdict(v) for k, v in self.ordres.items()},
                "derniers_cours": self.derniers_cours}

    def restaurer(self, e: dict | None) -> None:
        if not e:
            return
        self.capital = e.get("capital", self.capital)
        self.cash = e.get("cash", self.capital)
        self.positions = {k: Position(**v) for k, v in e.get("positions", {}).items()}
        self.ordres = {k: Ordre(**v) for k, v in e.get("ordres", {}).items()}
        self.derniers_cours = e.get("derniers_cours", {})

    def valeur(self) -> float:
        return self.cash + sum(p.quantite * self.derniers_cours.get(s, p.entree) for s, p in self.positions.items())

    # ------------------------------------------------------------- opérations
    def _vendre(self, p: Position, qte: float, prix: float) -> None:
        montant = qte * prix * (1 - self.cfg.frais_pct / 100)
        self.cash += montant
        p.encaisse += montant
        p.quantite -= qte

    def _cloturer(self, date: str, p: Position, prix: float, motif: str) -> dict:
        self._vendre(p, p.quantite, prix)
        res_r = (p.encaisse - p.cout) / (p.quantite_init * p.risque)
        trade = {"symbole": p.symbole, "setup": p.setup, "score": p.score, "date_entree": p.date_entree,
                 "date_sortie": date, "entree": p.entree, "stop_initial": p.stop_initial, "sortie": prix,
                 "motif": motif, "R": round(res_r, 3), "jours": p.jours, "gain": round(p.encaisse - p.cout, 2),
                 "rendement_pct": round((p.encaisse / p.cout - 1) * 100, 2), "t1_touche": p.t1_touche}
        self.journal.append(trade)
        del self.positions[p.symbole]
        return {"type": "SORTIE", "date": date, "symbole": p.symbole, "trade": trade}

    def jour(self, date: str, barres: dict, signaux: list[dict]) -> list[dict]:
        """barres : {symbole: {open, high, low, close, atr, seances_resultats}} pour le jour J.
        signaux : [{symbole, setup, score, stop, close, atr}] calculés à la clôture de J."""
        cfg = self.cfg
        ev: list[dict] = []

        # 1a. Sorties prévues la veille : vente à l'ouverture
        for s in list(self.positions):
            p = self.positions[s]
            if p.sortie_prevue and s in barres:
                ev.append(self._cloturer(date, p, barres[s]["open"], p.sortie_prevue))

        # 1b. Achats décidés la veille : exécution à l'ouverture
        valeur = self.valeur()
        for s, o in list(self.ordres.items()):
            del self.ordres[s]
            b = barres.get(s)
            if b is None:
                continue
            ouv = b["open"]
            if ouv > o.max_ouverture or ouv <= o.stop:
                motif = "ouverture trop haute" if ouv > o.max_ouverture else "ouverture sous le stop"
                ev.append({"type": "ANNULE", "date": date, "symbole": s, "ordre": asdict(o), "ouverture": ouv, "motif": motif})
                continue
            risque = ouv - o.stop
            qte = (valeur * cfg.risque_pct / 100) / risque
            qte = min(qte, valeur * cfg.poids_max_pct / 100 / ouv, self.cash / (ouv * (1 + cfg.frais_pct / 100)))
            if qte * ouv < valeur * 0.01:
                ev.append({"type": "ANNULE", "date": date, "symbole": s, "ordre": asdict(o), "ouverture": ouv,
                           "motif": "pas assez de liquidités"})
                continue
            cout = qte * ouv * (1 + cfg.frais_pct / 100)
            self.cash -= cout
            p = Position(symbole=s, setup=o.setup, score=o.score, date_signal=o.date_signal, date_entree=date,
                         entree=ouv, stop=o.stop, stop_initial=o.stop, t1=ouv + cfg.objectif_r * risque,
                         quantite=qte, quantite_init=qte, risque=risque, plus_haut=ouv, cout=cout)
            self.positions[s] = p
            ev.append({"type": "ACHAT", "date": date, "symbole": s, "pos": asdict(p)})

        # 2. Suivi des positions sur la séance
        for s in list(self.positions):
            p = self.positions[s]
            b = barres.get(s)
            if b is None:
                continue
            p.jours += 1
            if b["low"] <= p.stop:
                prix = p.stop if b["open"] > p.stop else b["open"]
                motif = "SUIVEUR" if p.stop > p.entree * 1.001 else ("BE" if p.t1_touche else "STOP")
                ev.append(self._cloturer(date, p, prix, motif))
                continue
            if not p.t1_touche and b["high"] >= p.t1:
                prix = max(p.t1, b["open"])
                self._vendre(p, p.quantite / 2, prix)
                p.t1_touche = True
                p.stop = max(p.stop, p.entree)
                ev.append({"type": "T1", "date": date, "symbole": s, "prix": prix, "pos": asdict(p)})
            p.plus_haut = max(p.plus_haut, b["close"])
            suiveur = p.plus_haut - cfg.suiveur_atr * b["atr"]
            if np.isfinite(suiveur) and suiveur > p.stop:
                ancien = p.stop
                p.stop = suiveur
                if p.stop - ancien >= 0.02 * b["close"] or (ancien <= p.entree < p.stop):
                    ev.append({"type": "STOP_MONTE", "date": date, "symbole": s, "ancien": ancien, "pos": asdict(p)})
            if p.jours >= cfg.duree_max and not p.sortie_prevue:
                p.sortie_prevue = "DUREE"
                ev.append({"type": "SORTIE_PREVUE", "date": date, "symbole": s, "motif": "DUREE",
                           "cours": b["close"], "pos": asdict(p)})
            nb = b.get("seances_resultats", np.inf)
            if 0 <= nb <= 3 and not p.alerte_resultats:
                p.alerte_resultats = True
                ev.append({"type": "RESULTATS", "date": date, "symbole": s, "seances": int(nb),
                           "cours": b["close"], "pos": asdict(p)})

        for s, b in barres.items():
            self.derniers_cours[s] = b["close"]

        # 3. Nouveaux signaux pour l'ouverture de demain
        places = cfg.max_positions - len(self.positions) - len(self.ordres)
        for sg in sorted(signaux, key=lambda x: -x["score"]):
            if places <= 0 or sum(1 for e in ev if e["type"] == "SIGNAL") >= cfg.max_entrees_jour:
                break
            if sg["symbole"] in self.positions or sg["symbole"] in self.ordres:
                continue
            o = Ordre(symbole=sg["symbole"], setup=sg["setup"], score=float(sg["score"]), date_signal=date,
                      prix_signal=sg["close"], stop=float(sg["stop"]),
                      max_ouverture=sg["close"] + cfg.ecart_ouverture_atr * sg["atr"])
            self.ordres[o.symbole] = o
            places -= 1
            ev.append({"type": "SIGNAL", "date": date, "symbole": o.symbole, "ordre": asdict(o), "signal": sg})
        return ev


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    r = np.array([t["R"] for t in trades], dtype=float)
    gains, pertes = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": int(len(r)), "gagnants": float((r > 0).mean() * 100), "esperance": float(r.mean()),
            "total": float(r.sum()), "pf": float(gains / pertes) if pertes > 0 else float("inf"),
            "jours": float(np.mean([t["jours"] for t in trades])),
            "rendement_moyen": float(np.mean([t["rendement_pct"] for t in trades]))}
