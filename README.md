# Agent de signaux NVIDIA (NVDA)

Agent qui analyse NVIDIA toutes les 5 minutes pendant la séance de Wall Street, comme le ferait un trader : plusieurs unités de temps, contexte de marché, événements, gestion du risque. Il t'envoie ses alertes sur iPhone via l'app ntfy.

Signaux techniques uniquement. Ce n'est pas un conseil en investissement.

## Ta journée type (heure de Paris)

| Heure | Message |
|---|---|
| 15h05 à 15h30 | 🌅 **Avant l'ouverture** : pré-marché, futures Nasdaq, VIX, niveaux clés, annonces du jour, actus, biais technique |
| 15h30 à 22h00 | 🟢 / 🔴 **Signal** avec entrée, stop, 2 objectifs, taille de position, raisons pour et contre |
| Pendant la séance | 🎯 **Objectif 1 atteint** (stop remonté au prix d'entrée), 🏆 objectif 2, ❌ stop, 🔔 sortie de fin de séance |
| Pendant la séance | ⚡ **Mouvement brusque** (plus de 2,5 % en 30 min) avec la dernière actu |
| 22h00 à 22h45 | 📊 **Bilan** : séance, signaux du jour et résultats, performance des 20 derniers signaux |

Toucher une alerte ouvre le graphique NVDA sur TradingView.

Deux fois par an, pendant environ 2 semaines (mars et fin octobre), tout est décalé d'une heure plus tôt. L'agent le gère seul.

## Ce que l'agent analyse

**5 configurations de trading**, chacune en achat et en vente :

- **Rebond dans la tendance** : repli sur la moyenne 21 ou le VWAP dans une tendance, puis reprise.
- **Cassure du range d'ouverture** : première clôture au-delà du plus haut ou du plus bas des 30 premières minutes.
- **Cassure du niveau de la veille** : première clôture au-delà du plus haut ou du plus bas de la veille.
- **Faux départ repris** : le niveau de la veille est enfoncé puis repris avec force (piège à vendeurs ou à acheteurs).
- **Retour vers la moyenne** : excès sous ou au-dessus des bandes VWAP, RSI extrême, puis retournement.

**Une note sur 100**, qui part de 50 et s'ajuste avec 18 facteurs :

- Tendance de fond (moyennes 50 et 200 jours) et tendance 15 minutes
- Force de la tendance (ADX), adaptée au type de configuration
- Nasdaq 100 (QQQ) et semi-conducteurs (SMH) dans le même sens ou non
- Force relative de NVIDIA face à son secteur
- Volume comparé à la normale **de la même heure** (le volume intraday suit une courbe en U)
- Divergences RSI, momentum MACD, extension par rapport au VWAP
- Place disponible jusqu'au prochain obstacle (niveaux de la veille, de la séance, 20 jours, moyennes mobiles)
- Taille du stop, heure de la journée, VIX
- Résultats NVIDIA (la veille, le jour J, le lendemain) et annonces macro (Fed, inflation, emploi)
- Historique récent de la configuration sur les 60 dernières séances, recalculé chaque matin

Un signal part si la note atteint 65 (note B) ou 80 (note A). Si achat et vente sont trop proches, l'agent s'abstient.

## Gestion du risque intégrée

- **Stop** placé sous la structure (plus bas récent, milieu du range) et jamais à moins de 2,5 fois la volatilité 5 minutes.
- **Objectif 1** à 1 R (R = distance entrée-stop). Plan : sortir la moitié, remonter le stop au prix d'entrée.
- **Objectif 2** à 2 R, ou juste avant le prochain obstacle s'il est entre 1,2 et 2,5 R.
- **Une seule position suivie à la fois**, 4 signaux maximum par séance, aucune position gardée le soir.
- **Taille de position** calculée si tu renseignes ton capital (voir Réglages).

## Ce que disent les tests (à lire avant de trader)

Mesuré le 5 novembre 2026 sur les 60 dernières séances, frais de 0,03 % inclus :

- **NVIDIA** : 33 signaux, 45 % gagnants, espérance -0,02 R par signal. Soit l'équilibre.
- **Validation sur 4 autres valeurs** du secteur (AMD, Broadcom, TSMC, Micron) pour éviter de sur-optimiser NVIDIA : résultats entre -0,08 R et +0,23 R par signal.
- La note ne prédit pas mieux le résultat quand elle monte. Les seuls facteurs qui aident nettement sur les 5 valeurs : un volume au moins 2 fois supérieur à la normale et une tendance très forte (ADX au-dessus de 35).

Conclusion directe : aucun ensemble de règles techniques ne bat le marché de façon fiable en intraday. L'agent te fait gagner du temps, structure tes décisions et protège ton capital. Il ne remplace pas ton jugement.

Recommandations :

- Suis les signaux **sans argent réel pendant 3 à 4 semaines**. Le bilan du soir tient les comptes.
- Ensuite, risque au maximum **0,5 à 1 % de ton capital** par signal.
- Relance le backtest une fois par mois (voir plus bas).

## Installation

1. App **ntfy** sur ton iPhone, abonnée à ton canal secret.
2. Dans le dépôt GitHub : **Settings > Secrets and variables > Actions**.
   - Onglet **Secrets** : `NTFY_TOPIC` = ton nom de canal. Optionnel : `TWELVEDATA_API_KEY` (clé gratuite sur twelvedata.com, plus fiable que Yahoo depuis GitHub).
   - Onglet **Variables** : les réglages ci-dessous, si tu veux changer les valeurs par défaut.
3. Onglet **Actions > Agent NVDA > Run workflow** : mode `test` pour recevoir une notification, mode `force` pour une analyse immédiate, mode `backtest` pour la mesure sur 60 séances (résultat dans le journal de l'exécution).

## Réglages (variables GitHub)

| Variable | Défaut | Effet |
|---|---|---|
| `CAPITAL_EUR` | vide | Ton capital en euros. Active le calcul de taille de position. |
| `RISQUE_PCT` | 1 | % du capital risqué par signal. |
| `SEUIL_SCORE` | 65 | Note minimum pour alerter. Plus haut = moins de signaux. |
| `MAX_SIGNAUX_JOUR` | 4 | Nombre maximum de signaux par séance. |
| `STOP_MIN_ATR` | 2,5 | Distance minimum du stop, en volatilité 5 min. |
| `FRAIS_PCT` | 0,03 | Tes frais aller-retour en %. Mets la vraie valeur de ton courtier (frais de change compris). |
| `SEUIL_MOUVEMENT` | 2,5 | % sur 30 min pour l'alerte de mouvement brusque. |

Utilise un point pour les décimales dans GitHub (par exemple `0.5`).

## Calendrier des annonces

Le fichier `evenements.json` contient les décisions de la Fed, l'inflation (CPI) et l'emploi jusqu'à fin 2027, d'après les calendriers officiels (federalreserve.gov et bls.gov). Les dates de la Fed pour 2027 sont provisoires. Les dates de résultats NVIDIA sont aussi récupérées automatiquement chaque jour.

## Sur ton ordinateur (optionnel)

```bash
pip install -r requirements.txt
export NTFY_TOPIC=ton-canal
python -m nvda_agent --test       # notification de test
python -m nvda_agent --backtest   # mesure sur 60 séances
python -m nvda_agent --force --dry-run   # analyse immédiate, sans envoyer
python -m pytest -q               # 16 tests automatiques
```

## Fiabilité

- Aucune donnée du futur dans les calculs : vérifié par un test automatique qui recalcule tout bougie par bougie.
- Le backtest utilise exactement le même moteur que le suivi en direct.
- Si les données manquent 3 fois de suite, tu reçois une alerte, puis une autre quand tout repart.
- Si une cotation est figée plus de 20 minutes, tu es prévenu.
- GitHub peut décaler une exécution de quelques minutes aux heures chargées. L'agent rattrape les bougies manquées et signale les alertes en retard.
- Sans activité sur le dépôt pendant 60 jours, GitHub met l'automatisation en pause et t'envoie un mail. Un clic sur **Enable workflow** relance tout.
