# Agent de swing trading (NVIDIA + liste de valeurs)

Chaque soir après la clôture de Wall Street, l'agent analyse NVIDIA et une liste de grandes valeurs tech. Il t'envoie sur iPhone (app ntfy) uniquement ce qu'il y a à faire : un achat pour le lendemain, un stop à remonter, une vente.

- Horizon : quelques semaines (8 semaines au maximum).
- Achats seulement : pas de vente à découvert, compatible avec tous les courtiers.
- Signaux techniques uniquement. Ce n'est pas un conseil en investissement.

## Ce que tu reçois

L'analyse tombe vers **22h37 (heure de Paris) en hiver**, 23h37 en été. Pas d'alerte s'il n'y a rien à faire.

| Alerte | Ce que tu fais |
|---|---|
| 🟢 **ACHAT** | Le lendemain : achat à l'ouverture, puis tu poses le stop indiqué tout de suite |
| ✅ Achat exécuté | Confirmation avec l'objectif recalculé sur le vrai prix d'ouverture |
| ⛔ Achat annulé | L'ouverture était trop haute : tu n'achètes pas |
| 🎯 **Objectif 1 atteint** | Tu vends la moitié et tu remontes le stop au prix d'entrée |
| ⬆️ **Remonte ton stop** | Tu modifies ton ordre stop chez ton courtier |
| ❌ / 🏆 Sortie | Le stop a été touché : la position est close |
| 🔔 **Vends demain** | 8 semaines écoulées : vente à l'ouverture |
| ⚠️ Résultats à venir | L'entreprise publie bientôt : tu décides d'alléger ou non |
| 📊 Bilan du vendredi | Marché, positions, classement de force relative, agenda des 2 semaines |

Toucher une alerte ouvre le graphique sur TradingView.

## Comment appliquer un signal

1. Le soir : tu reçois l'alerte ACHAT avec le prix maximum à l'ouverture, le stop et l'objectif.
2. Le lendemain à 15h30 : achat au marché à l'ouverture. Si l'ouverture dépasse le prix maximum indiqué, tu n'achètes pas.
3. Juste après l'achat : ordre **stop** de vente au niveau indiqué. Il te protège même si tu ne regardes pas.
4. Ordre **limite** de vente sur la moitié des actions à l'objectif 1. Optionnel mais pratique.
5. Ensuite, tu suis les alertes : stop à remonter, vente à 8 semaines.

## La stratégie

**3 configurations d'achat**, toutes dans une tendance haussière (cours au-dessus de la moyenne 200 jours, qui monte) :

- **Repli dans une tendance haussière** : le cours revient vers sa moyenne 20 jours ou se détend (RSI), puis repart avec une clôture au-dessus du plus haut de la veille. C'est la configuration principale.
- **Cassure d'un plus haut de 50 séances**, avec un volume au moins 1,4 fois supérieur à la moyenne.
- **Reprise de la moyenne 50 jours** après une correction.

**Une note sur 100** qui tient compte de : tendance du Nasdaq, tendance des semi-conducteurs, force relative sur 6 mois face au Nasdaq, moyenne 30 semaines, force de la tendance (ADX), distance au plus haut annuel, volume, surextension, RSI, largeur du stop, publication de résultats imminente. Un signal part à partir de 60. Note A à partir de 75.

**Gestion du risque** :

- Stop entre 1,5 et 3,5 fois la volatilité journalière, sous le dernier creux.
- Taille calculée pour perdre 1 % du capital si le stop est touché, et 25 % du capital au maximum par valeur.
- Objectif 1 à 2 R (2 fois la distance au stop) : vente de la moitié, stop au prix d'entrée.
- Stop suiveur : plus haute clôture moins 3 fois la volatilité. Il ne redescend jamais.
- 5 positions au maximum, 2 nouveaux achats par jour au maximum.
- Pas de nouvel achat à moins de 5 séances d'une publication de résultats.

## Résultats sur 20 ans (2006 à novembre 2026)

Backtest avec exactement les règles ci-dessus, frais de 0,10 % par ordre inclus.

| | Par an | Pire baisse | Capital investi en moyenne |
|---|---|---|---|
| **Stratégie** (10 valeurs suivies) | **7,0 %** | **-27 %** | 44 % |
| Nasdaq 100 (QQQ) gardé en permanence | 15,0 % | -53 % | 100 % |
| Les 10 valeurs gardées à parts égales | 27,3 % | -67 % | 100 % |

Les signaux un par un :

- 889 signaux, 41 % gagnants, **+0,20 R en moyenne** par signal (soit +1,1 % par position).
- Positif sur les 10 valeurs, et sur les deux périodes : +0,11 R de 2006 à 2015, +0,27 R depuis 2016.
- **Contrôle sur 15 autres valeurs**, dont des perdantes (Intel, Cisco, IBM, General Electric, Pfizer) : +0,16 R par signal. L'avantage ne vient donc pas seulement du choix de valeurs gagnantes.
- La configuration « cassure » est la moins fiable (-0,08 R sur 20 ans). Sa note est réduite de 8 points.

**Ce qu'il faut en retenir, sans enjoliver :**

- La stratégie a un vrai avantage par signal, mais elle gagne **moins que garder le Nasdaq** sur 20 ans. Elle n'est investie que 44 % du temps et ne risque que 1 % par position.
- En échange, sa pire baisse est **deux fois plus faible**, et ton capital est libre plus de la moitié du temps.
- Les 10 valeurs suivies ont été choisies aujourd'hui, en sachant qu'elles ont énormément monté. Leurs chiffres d'achat-conservation sont donc flatteurs (biais du survivant).
- Pour plus de rendement, tu peux monter le risque par position : à 2 %, environ +9,5 % par an mais une pire baisse vers -38 %.
- Le passé ne garantit rien. Commence par suivre les signaux **sans argent réel pendant 1 à 2 mois**.

Relance le backtest quand tu veux : onglet Actions, mode `backtest`.

## Réglages (Settings > Secrets and variables > Actions > Variables)

| Variable | Défaut | Effet |
|---|---|---|
| `VALEURS` | NVDA,AMD,AVGO,TSM,ASML,MU,MSFT,GOOGL,AMZN,META | Les valeurs suivies, séparées par des virgules (symboles US) |
| `CAPITAL_EUR` | vide | Ton capital en euros. Active le calcul du nombre d'actions |
| `RISQUE_PCT` | 1 | % du capital perdu si un stop est touché |
| `MAX_POSITIONS` | 5 | Positions ouvertes en même temps |
| `SEUIL_SCORE` | 60 | Note minimum pour un signal d'achat |
| `DUREE_MAX` | 40 | Durée maximale en séances (40 = 8 semaines) |
| `OBJECTIF_R` | 2 | Objectif 1 en multiple du risque |
| `FRAIS_PCT` | 0.1 | Tes frais par ordre en %, change compris |

Le secret `NTFY_TOPIC` contient ton canal ntfy.

## Modes manuels (onglet Actions > Agent swing > Run workflow)

- `test` : notification de test sur ton iPhone.
- `apercu` : analyse complète de la dernière séance, affichée dans le journal, sans rien envoyer ni modifier.
- `backtest` : mesure sur 20 ans avec le contrôle sur 15 autres valeurs.
- `normal` : le passage du soir, lancé à la main.

## Limites

- L'agent suit un **portefeuille modèle** : il suppose que tu appliques tous les signaux. Si tu en sautes un, ignore ses alertes de suivi.
- Le stop ne protège pas d'un écart à l'ouverture (résultats, annonce surprise). D'où l'alerte avant les résultats.
- Les cours viennent de Yahoo Finance, ajustés des divisions d'actions et des dividendes.
- Calendrier macro dans `evenements.json` (Fed, inflation, emploi jusqu'à fin 2027, sources officielles).

## Sur ton ordinateur (optionnel)

```bash
pip install -r requirements.txt
python -m nvda_agent --force --dry-run   # analyse de la dernière séance, sans envoi
python -m nvda_agent --backtest          # 20 ans de backtest
python -m pytest -q                      # 16 tests automatiques
```
