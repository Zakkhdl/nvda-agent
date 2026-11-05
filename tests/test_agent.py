"""Tests hors réseau. Lancer : python -m pytest -q"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from nvda_agent import agent as AG
from nvda_agent import data as D
from nvda_agent.config import NY, Config
from nvda_agent.data import Marche
from nvda_agent.engine import Moteur, rejouer, stats
from nvda_agent.features import construire
from nvda_agent.strategy import analyser


# ---------------------------------------------------------------------------
# Données simulées
# ---------------------------------------------------------------------------
def _seances(n_jours: int, fin: str = "2026-11-05", graine: int = 1, depart: float = 180.0):
    rng = np.random.default_rng(graine)
    jours = pd.bdate_range(end=fin, periods=n_jours)
    lignes, daily, prix = [], [], depart
    for k, j in enumerate(jours):
        derive = 0.0015 if (k // 15) % 2 == 0 else -0.0012
        o = prix * (1 + rng.normal(0, 0.008))
        p, barres = o, []
        for s in range(78):
            ts = pd.Timestamp(j, tz=NY) + pd.Timedelta(hours=9, minutes=30 + 5 * s)
            c = p * (1 + rng.normal(derive / 78, 0.0025))
            h = max(p, c) * (1 + abs(rng.normal(0, 0.0008)))
            lo = min(p, c) * (1 - abs(rng.normal(0, 0.0008)))
            v = rng.lognormal(12, 0.4) * (2.5 if s < 4 or s > 73 else 1.0)
            barres.append((ts, p, h, lo, c, v))
            p = c
        lignes += barres
        daily.append((pd.Timestamp(j, tz=NY), o, max(b[2] for b in barres), min(b[3] for b in barres), p,
                      sum(b[5] for b in barres)))
        prix = p
    mk = lambda r: pd.DataFrame(r, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    return mk(lignes), mk(daily)


def _marche(n_intraday: int = 40, graine: int = 1) -> Marche:
    intra, daily_recent = _seances(n_intraday, graine=graine)
    _, daily_ancien = _seances(260, fin=(daily_recent.index[0] - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                               graine=graine + 10)
    daily = pd.concat([daily_ancien, daily_recent])
    ref_m, _ = _seances(n_intraday, graine=graine + 1, depart=600)
    ref_s, _ = _seances(n_intraday, graine=graine + 2, depart=450)
    vix = intra[["close"]].copy()
    vix["close"] = 20 + np.cumsum(np.random.default_rng(graine).normal(0, 0.05, len(vix)))
    for c in ("open", "high", "low"):
        vix[c] = vix["close"]
    vix["volume"] = 0.0
    norm = D.normaliser
    return Marche(nvda=norm(intra), daily=norm(daily), ref_marche=norm(ref_m), ref_secteur=norm(ref_s),
                  vix=norm(vix), source="SIMULATION")


@pytest.fixture(scope="module")
def marche():
    return _marche()


# ---------------------------------------------------------------------------
# 1. Aucune information du futur
# ---------------------------------------------------------------------------
def test_aucune_fuite_du_futur(marche):
    complet = construire(marche)
    for coupe in (len(marche.nvda) - 1, len(marche.nvda) - 37, len(marche.nvda) - 80):
        m2 = Marche(**{**marche.__dict__})
        m2.nvda = marche.nvda.iloc[:coupe]
        m2.ref_marche = marche.ref_marche.iloc[:coupe]
        m2.ref_secteur = marche.ref_secteur.iloc[:coupe]
        partiel = construire(m2)
        a = complet.iloc[:coupe]
        for col in partiel.columns:
            if partiel[col].dtype.kind in "fiub":
                x, y = a[col].to_numpy(dtype=float), partiel[col].to_numpy(dtype=float)
                assert np.allclose(x, y, equal_nan=True, rtol=1e-9, atol=1e-9), f"fuite du futur : {col}"


def test_signaux_identiques_en_direct_et_en_backtest(marche):
    """Un signal donné à la bougie t ne doit pas changer quand les bougies suivantes arrivent."""
    complet = analyser(construire(marche))
    coupe = len(marche.nvda) - 50
    m2 = Marche(**{**marche.__dict__})
    m2.nvda = marche.nvda.iloc[:coupe]
    partiel = analyser(construire(m2))
    a, b = complet.meilleur["score"][:coupe], partiel.meilleur["score"]
    assert np.array_equal(np.nan_to_num(a, nan=-9), np.nan_to_num(b, nan=-9))


# ---------------------------------------------------------------------------
# 2. Indicateurs
# ---------------------------------------------------------------------------
def test_contexte_journalier_vient_de_la_veille(marche):
    f = construire(marche)
    derniere_seance = f["sess"].iloc[-1]
    veille = marche.daily[marche.daily.index.normalize().tz_localize(None) < derniere_seance].iloc[-1]
    assert f["veille_close"].iloc[-1] == pytest.approx(veille["close"])
    assert f["veille_haut"].iloc[-1] == pytest.approx(veille["high"])


def test_range_ouverture_disponible_a_10h(marche):
    f = construire(marche)
    jour = f[f["sess"] == f["sess"].iloc[-1]]
    assert jour["or_haut"].iloc[:6].isna().all()
    assert jour["or_haut"].iloc[6] == pytest.approx(jour["high"].iloc[:6].max())


def test_valeurs_plausibles(marche):
    f = construire(marche).iloc[-500:]
    assert f["rsi"].between(0, 100).all()
    assert (f["atr5"] > 0).all()
    assert f["adx15"].between(0, 100).all()
    assert f["rvol"].gt(0).all()


# ---------------------------------------------------------------------------
# 3. Moteur de suivi
# ---------------------------------------------------------------------------
def _moteur():
    return Moteur(seuil=60, max_jour=4, frais_pct=0.0)


CAND_L = {"cle": "PULLBACK_L", "sens": 1, "score": 70.0, "stop": 99.0, "t1": 101.0, "t2": 102.0}


def test_objectif_1_puis_objectif_2():
    m = _moteur()
    ev = m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    assert ev[0]["type"] == "OUVERTURE"
    ev = m.pas(1, "t1", "J", 11, 100, 101.2, 100.5, 101, False, None)
    assert ev[0]["type"] == "T1" and m.pos.stop == 100
    ev = m.pas(2, "t2", "J", 12, 101, 102.5, 100.8, 102.2, False, None)
    assert ev[0]["type"] == "T2"
    assert ev[0]["trade"]["R"] == pytest.approx(0.5 * 1 + 0.5 * 2)


def test_stop_puis_pire_cas():
    m = _moteur()
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    ev = m.pas(1, "t1", "J", 11, 100, 101.5, 98.5, 100, False, None)  # stop ET objectif dans la même bougie
    assert ev[0]["type"] == "STOP" and ev[0]["trade"]["R"] == pytest.approx(-1)


def test_ouverture_sous_le_stop():
    m = _moteur()
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    ev = m.pas(1, "t1", "J", 11, 98.0, 98.5, 97.5, 98, False, None)
    assert ev[0]["trade"]["sortie"] == 98.0 and ev[0]["trade"]["R"] == pytest.approx(-2)


def test_retour_au_prix_entree_apres_objectif_1():
    m = _moteur()
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    m.pas(1, "t1", "J", 11, 100, 101.1, 100.2, 101, False, None)
    ev = m.pas(2, "t2", "J", 12, 100.5, 100.6, 99.9, 100, False, None)
    assert ev[0]["type"] == "BE" and ev[0]["trade"]["R"] == pytest.approx(0.5)


def test_vente_symetrique():
    m = _moteur()
    cand = {"cle": "ORB_S", "sens": -1, "score": 70.0, "stop": 101.0, "t1": 99.0, "t2": 98.0}
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, cand)
    m.pas(1, "t1", "J", 11, 100, 100.2, 98.9, 99, False, None)
    ev = m.pas(2, "t2", "J", 12, 99, 99.1, 97.9, 98, False, None)
    assert ev[0]["type"] == "T2" and ev[0]["trade"]["R"] == pytest.approx(1.5)


def test_cloture_fin_de_seance_et_limite_quotidienne():
    m = Moteur(seuil=60, max_jour=1, frais_pct=0.0)
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    ev = m.pas(1, "t1", "J", 77, 100, 100.4, 99.8, 100.3, True, None)
    assert ev[0]["type"] == "FIN" and ev[0]["trade"]["R"] == pytest.approx(0.3)
    assert m.pas(2, "t2", "J", 20, 100, 100, 100, 100, False, CAND_L) == []  # limite atteinte


def test_frais_deduits():
    m = Moteur(seuil=60, max_jour=4, frais_pct=0.1)
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    ev = m.pas(1, "t1", "J", 11, 100, 100.1, 98.9, 99, False, None)
    assert ev[0]["trade"]["R"] == pytest.approx(-1 - 0.1)


def test_persistance_du_moteur():
    m = _moteur()
    m.pas(0, "t0", "J", 10, 100, 100, 100, 100, False, CAND_L)
    m2 = _moteur()
    m2.restaurer(json.loads(json.dumps(m.etat())))
    assert m2.pos.entree == 100 and m2.nb_jour == 1


# ---------------------------------------------------------------------------
# 4. Agent complet sur une séance simulée
# ---------------------------------------------------------------------------
def test_phases():
    t = lambda h, mi, j=5: pd.Timestamp(dt.datetime(2026, 11, j, h, mi), tz=NY)
    assert AG.phase(t(9, 10)) == "pre"
    assert AG.phase(t(9, 30)) == "seance"
    assert AG.phase(t(15, 59)) == "seance"
    assert AG.phase(t(16, 10)) == "post"
    assert AG.phase(t(17, 0)) == "ferme"
    assert AG.phase(t(11, 0, j=7)) == "ferme"  # samedi


def test_seance_complete(tmp_path, monkeypatch, marche):
    monkeypatch.setattr(D, "dates_resultats", lambda s: [])
    monkeypatch.setattr(D, "actualites", lambda s, n=3: [{"titre": "Titre test", "source": "Test", "date": ""}])
    monkeypatch.setattr(D, "dernier_cours", lambda s: 1.10)
    envoyes = []
    monkeypatch.setattr(AG, "envoyer", lambda cfg, t, c, *a, **k: envoyes.append((t, c)) or True)
    ev_file = tmp_path / "ev.json"
    ev_file.write_text(json.dumps({"evenements": []}))
    cfg = Config(state_file=str(tmp_path / "state.json"), events_file=str(ev_file), seuil=55, capital_eur=10000)
    jour = marche.nvda.index[-1].normalize()
    debut = jour + pd.Timedelta(hours=9, minutes=35, seconds=20)
    for k in range(0, 82):
        now = debut + pd.Timedelta(minutes=5 * k)
        m2 = Marche(**{**marche.__dict__})
        AG.executer(cfg, now=now.to_pydatetime(), dry_run=True, marche=m2)
    etat = json.loads((tmp_path / "state.json").read_text())
    assert etat["erreurs"] == 0
    assert etat["recap_date"] == jour.date().isoformat()
    assert etat["calib"]["date"] == jour.date().isoformat()
    titres = [t for t, _ in envoyes]
    assert any("bilan" in t for t in titres)
    import re
    for t, c in envoyes:
        assert not re.search(r"\bnan\b|\binf\b", (t + c).lower()), f"valeur manquante dans : {t}"
    assert etat["moteur"]["pos"] is None  # aucune position laissée ouverte le soir


def test_backtest_tourne(marche, tmp_path, monkeypatch):
    from nvda_agent import backtest as B
    ev_file = tmp_path / "ev.json"
    ev_file.write_text(json.dumps({"evenements": [{"date": "2026-11-03", "type": "RESULTATS"}]}))
    cfg = Config(events_file=str(ev_file), seuil=55)
    r = B.lancer(cfg, csv=str(tmp_path / "bt.csv"), marche=marche)
    assert "brut" in r
