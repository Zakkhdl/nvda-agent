"""Tests hors réseau. Lancer : python -m pytest -q"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re

import numpy as np
import pandas as pd
import pytest

from nvda_agent import agent as AG
from nvda_agent import data as D
from nvda_agent.config import NY, Config
from nvda_agent.features import preparer
from nvda_agent.portfolio import Portefeuille, stats
from nvda_agent.simulation import preparer_tout, simuler
from nvda_agent.strategy import evaluer, seances_avant_resultats

VALEURS = ("AAA", "BBB", "NVDA")


# ---------------------------------------------------------------------------
# Données simulées : tendances haussières entrecoupées de replis
# ---------------------------------------------------------------------------
def _serie(n: int, graine: int, depart: float = 100.0, fin: str = "2026-11-04") -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    jours = pd.bdate_range(end=fin, periods=n)
    derive = np.where((np.arange(n) // 60) % 3 == 2, -0.0015, 0.0012)
    ret = derive + rng.normal(0, 0.018, n)
    close = depart * np.exp(np.cumsum(ret))
    ouverture = close * np.exp(rng.normal(0, 0.006, n))
    haut = np.maximum(close, ouverture) * (1 + np.abs(rng.normal(0, 0.008, n)))
    bas = np.minimum(close, ouverture) * (1 - np.abs(rng.normal(0, 0.008, n)))
    vol = rng.lognormal(15, 0.35, n)
    df = pd.DataFrame({"open": ouverture, "high": haut, "low": bas, "close": close, "volume": vol}, index=jours)
    df.index.name = "date"
    return df


@pytest.fixture(scope="module")
def donnees():
    d = {s: _serie(900, k + 1) for k, s in enumerate(VALEURS)}
    d["QQQ"] = _serie(900, 50, 300)
    d["SMH"] = _serie(900, 51, 200)
    return d


@pytest.fixture(scope="module")
def cfg():
    return Config(valeurs=VALEURS, frais_pct=0.0)


# ---------------------------------------------------------------------------
# 1. Aucune information du futur
# ---------------------------------------------------------------------------
def test_aucune_fuite_du_futur(donnees, cfg):
    s = "AAA"
    complet = evaluer(preparer(donnees[s], donnees["QQQ"], donnees["SMH"]), cfg, s, ["2026-06-01"])
    for coupe in (len(donnees[s]) - 1, len(donnees[s]) - 40, 500):
        tronque = {k: v.iloc[:coupe] for k, v in donnees.items()}
        partiel = evaluer(preparer(tronque[s], tronque["QQQ"], tronque["SMH"]), cfg, s, ["2026-06-01"])
        a = complet.iloc[:coupe]
        for col in partiel.columns:
            if partiel[col].dtype.kind in "fiub":
                assert np.allclose(a[col].to_numpy(float), partiel[col].to_numpy(float), equal_nan=True), col
        assert (a["setup"].to_numpy() == partiel["setup"].to_numpy()).all()


def test_des_signaux_existent(donnees, cfg):
    ev = preparer_tout(donnees, cfg)
    nb = sum((d["setup"] != "").sum() for d in ev.values())
    assert nb > 5
    for d in ev.values():
        sig = d[d["setup"] != ""]
        assert (sig["stop"] < sig["close"]).all()
        dist = (sig["close"] - sig["stop"]) / sig["atr"]
        assert dist.between(cfg.stop_min_atr - 1e-9, cfg.stop_max_atr + 1e-9).all()


def test_seances_avant_resultats():
    idx = pd.DatetimeIndex(["2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18"])
    nb = seances_avant_resultats(idx, ["2026-11-17", "2027-02-20"])
    assert list(nb[:3]) == [2, 1, 69] or list(nb[:2]) == [2, 1]
    assert nb[2] > 10  # le jour même, la prochaine publication est la suivante


# ---------------------------------------------------------------------------
# 2. Portefeuille modèle
# ---------------------------------------------------------------------------
def _b(o, h, l, c, atr=2.0, res=np.inf):
    return {"open": o, "high": h, "low": l, "close": c, "atr": atr, "seances_resultats": res}


def _sig(s="AAA", close=100.0, stop=95.0, score=70.0):
    return {"symbole": s, "setup": "REPLI", "score": score, "stop": stop, "close": close, "atr": 2.0}


def _pf(**k):
    return Portefeuille(dataclasses.replace(Config(valeurs=("AAA", "BBB")), frais_pct=0.0, **k), 100_000)


def test_achat_le_lendemain_a_l_ouverture_et_taille():
    pf = _pf()
    ev = pf.jour("2026-01-02", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    assert ev[0]["type"] == "SIGNAL" and not pf.positions
    ev = pf.jour("2026-01-05", {"AAA": _b(100, 101, 99, 100.5)}, [])
    assert ev[0]["type"] == "ACHAT"
    p = pf.positions["AAA"]
    assert p.entree == 100 and p.risque == 5
    assert p.quantite * p.risque == pytest.approx(1000)  # 1 % de 100 000
    assert p.t1 == pytest.approx(110)


def test_annulation_si_ouverture_trop_haute():
    pf = _pf()
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    ev = pf.jour("d2", {"AAA": _b(103, 104, 102, 103)}, [])  # max = 100 + 1 x 2
    assert ev[0]["type"] == "ANNULE" and not pf.positions


def test_stop_et_objectif_le_meme_jour_on_suppose_le_pire():
    pf = _pf()
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    pf.jour("d2", {"AAA": _b(100, 101, 99, 100)}, [])
    ev = pf.jour("d3", {"AAA": _b(100, 112, 94, 100)}, [])
    assert ev[0]["type"] == "SORTIE" and ev[0]["trade"]["R"] == pytest.approx(-1)


def test_objectif_1_puis_stop_au_prix_entree():
    pf = _pf()
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    pf.jour("d2", {"AAA": _b(100, 101, 99, 100)}, [])
    ev = pf.jour("d3", {"AAA": _b(105, 111, 104, 108)}, [])
    assert [e["type"] for e in ev][0] == "T1"
    assert pf.positions["AAA"].stop >= 100
    ev = pf.jour("d4", {"AAA": _b(104, 104, 99, 100)}, [])
    tr = ev[0]["trade"]
    assert tr["motif"] in ("BE", "SUIVEUR") and tr["R"] == pytest.approx(1.0, abs=0.35)


def test_stop_suiveur_ne_redescend_jamais():
    pf = _pf()
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    pf.jour("d2", {"AAA": _b(100, 101, 99, 100)}, [])
    stops = []
    for k, c in enumerate([103, 106, 109, 108, 107, 112]):
        pf.jour(f"d{k + 3}", {"AAA": _b(c - 1, c + 0.5, c - 1.5, c)}, [])
        if "AAA" in pf.positions:
            stops.append(pf.positions["AAA"].stop)
    assert all(b >= a for a, b in zip(stops, stops[1:]))


def test_sortie_apres_duree_maximale():
    pf = _pf(duree_max=3)
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    types = []
    for k in range(5):
        types += [e["type"] for e in pf.jour(f"d{k + 2}", {"AAA": _b(100.5, 101, 100, 100.5)}, [])]
    assert "SORTIE_PREVUE" in types and pf.journal and pf.journal[0]["motif"] == "DUREE"


def test_limites_positions_et_achats_par_jour():
    pf = _pf(max_positions=2, max_entrees_jour=1)
    ev = pf.jour("d1", {"AAA": _b(99, 101, 98, 100), "BBB": _b(99, 101, 98, 100)},
                 [_sig("AAA", score=70), _sig("BBB", score=80)])
    assert [e["symbole"] for e in ev if e["type"] == "SIGNAL"] == ["BBB"]


def test_persistance():
    pf = _pf()
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    pf.jour("d2", {"AAA": _b(100, 101, 99, 100)}, [])
    pf2 = _pf()
    pf2.restaurer(json.loads(json.dumps(pf.etat())))
    assert pf2.positions["AAA"].entree == 100 and pf2.cash == pytest.approx(pf.cash)


def test_frais():
    pf = Portefeuille(Config(valeurs=("AAA",), frais_pct=0.1), 100_000)
    pf.jour("d1", {"AAA": _b(99, 101, 98, 100)}, [_sig()])
    pf.jour("d2", {"AAA": _b(100, 101, 99, 100)}, [])
    ev = pf.jour("d3", {"AAA": _b(96, 96, 94, 95)}, [])
    assert ev[0]["trade"]["R"] < -1


# ---------------------------------------------------------------------------
# 3. Simulation et passage du soir
# ---------------------------------------------------------------------------
def test_simulation(donnees, cfg):
    ev = preparer_tout(donnees, cfg)
    pf, courbe, investi = simuler(ev, cfg)
    assert len(courbe) > 500 and (courbe > 0).all() and investi.between(0, 1.0001).all()
    assert stats(pf.journal)["n"] > 0


def test_soirees_successives(tmp_path, monkeypatch, donnees):
    monkeypatch.setattr(D, "dates_resultats", lambda s: ["2026-11-17"] if s == "NVDA" else [])
    monkeypatch.setattr(D, "eurusd", lambda: 1.10)
    envoyes = []
    monkeypatch.setattr(AG, "envoyer", lambda cfg, t, c, *a, **k: envoyes.append((t, c)) or True)
    ev_file = tmp_path / "ev.json"
    ev_file.write_text(json.dumps({"evenements": [{"date": "2026-11-10", "type": "CPI", "titre": "Inflation US"}]}))
    cfg = Config(valeurs=VALEURS, state_file=str(tmp_path / "s.json"), events_file=str(ev_file), capital_eur=20000)
    jours = donnees["AAA"].index[-60:]
    for j in jours:
        tronque = {k: v[v.index <= j] for k, v in donnees.items()}
        now = dt.datetime(j.year, j.month, j.day, 16, 40, tzinfo=NY)
        AG.executer(cfg, now=now, donnees=tronque)
    etat = json.loads((tmp_path / "s.json").read_text())
    assert etat["erreurs"] == 0 and etat["derniere_date"] == str(jours[-1].date())
    assert any(t.startswith("Bilan de la semaine") for t, _ in envoyes)
    for t, c in envoyes:
        assert not re.search(r"\bnan\b|\binf\b|n/d", (t + c).lower()), t
    # relancer la même soirée n'envoie rien de plus
    n = len(envoyes)
    AG.executer(cfg, now=now, donnees=tronque)
    assert len(envoyes) == n


def test_seance_en_cours_ignoree(tmp_path, monkeypatch, donnees):
    monkeypatch.setattr(D, "dates_resultats", lambda s: [])
    monkeypatch.setattr(AG, "envoyer", lambda *a, **k: True)
    cfg = Config(valeurs=VALEURS, state_file=str(tmp_path / "s.json"), events_file=str(tmp_path / "x.json"))
    j = donnees["AAA"].index[-1]
    AG.executer(cfg, now=dt.datetime(j.year, j.month, j.day, 11, 0, tzinfo=NY), donnees=donnees)
    etat = json.loads((tmp_path / "s.json").read_text())
    assert etat["derniere_date"] == str(donnees["AAA"].index[-2].date())


def test_backtest(donnees, cfg, capsys):
    from nvda_agent.backtest import lancer
    r = lancer(dataclasses.replace(cfg, valeurs=VALEURS), csv="", donnees=donnees, controle=False)
    assert r["stats"]["n"] > 0
    assert "BACKTEST" in capsys.readouterr().out
