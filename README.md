# Agent de signaux NVIDIA (NVDA)

Un agent qui analyse le cours de NVIDIA toutes les 5 minutes pendant la séance de Wall Street et t'envoie une alerte sur ton téléphone quand plusieurs signaux techniques s'alignent.

Signaux techniques uniquement. Ce n'est pas un conseil en investissement.

## Ce que tu reçois

- **Point d'ouverture** chaque jour vers 15h35 (heure de Paris) : écart d'ouverture, clôture de la veille, moyennes mobiles 50 et 200 jours, tendance de fond, volatilité moyenne.
- **Signal achat** (🟢) ou **signal vente** (🔴) quand le score de confluence atteint le seuil, avec la liste des raisons.
- **Mouvement brusque** (⚡) quand le cours bouge de plus de 2,5 % en 30 minutes.
- **Alerte technique** (⚠️) si les données sont indisponibles 3 fois de suite, puis un message quand tout repart.

Exemple d'alerte :

```
🟢 NVDA : signal achat (score 5/10)
Prix : 191,40 $ à 17h35
Pourquoi :
• RSI 5 min repasse au-dessus de 30 (sortie de survente)
• Rebond sur la bande de Bollinger basse
• Tendance de fond haussière (prix > MM50 > MM200)
Score opposé : 0/10
RSI 5 min : 34,5 | VWAP : 193,10 $
Volatilité moyenne (ATR) : 6,47 $ soit 3,4 %
Veille : haut 206,79 $, bas 199,68 $
Signal technique, pas un conseil.
```

## Comment le score fonctionne

L'agent travaille sur des bougies de 5 minutes. Il ne regarde que les bougies clôturées. Chaque condition ajoute des points côté achat ou côté vente.

| Condition | Achat | Vente |
|---|---|---|
| RSI 5 min sort de survente (repasse 30) ou de surachat (repasse 70) | +2 | +2 |
| RSI 5 min encore en survente ou en surachat | +1 | +1 |
| MACD croise sa ligne de signal | +2 | +2 |
| Rebond sur la bande de Bollinger basse ou rejet sur la haute | +2 | +2 |
| Prix encore hors de la bande de Bollinger | +1 | +1 |
| Prix croise le VWAP de la séance | +1 | +1 |
| Bougie dans le bon sens avec volume 1,5 fois supérieur à la moyenne | +1 | +1 |
| Tendance de fond journalière dans le bon sens (MM50 et MM200) | +1 | +1 |
| RSI journalier extrême (sous 35 ou au-dessus de 70) | +1 | +1 |
| Signal contre la tendance de fond | -1 | -1 |

Une alerte part si les 3 règles sont réunies :

- le score atteint le seuil (5 sur 10 par défaut),
- au moins un vrai déclencheur (+2) apparaît sur la bougie,
- le score du côté opposé est plus faible.

Pas plus d'une alerte du même type par heure. La tendance de fond utilise les chiffres de la veille, jamais de données futures.

## Installation sur GitHub (gratuit, ton PC peut rester éteint)

Compte 15 minutes.

### 1. Choisis comment recevoir les alertes

**Option ntfy (la plus simple, aucun compte)**

- Installe l'application **ntfy** sur ton téléphone (Android ou iPhone).
- Appuie sur **+** et abonne-toi à un nom de canal difficile à deviner, par exemple `nvda-z-7k2p9x4m`.
- Garde ce nom. C'est ton secret `NTFY_TOPIC`. Toute personne qui connaît ce nom peut lire tes alertes.

**Option Telegram**

- Dans Telegram, écris à **@BotFather**, tape `/newbot` et suis les étapes. Il te donne un token. C'est ton secret `TELEGRAM_BOT_TOKEN`.
- Envoie un message quelconque à ton nouveau bot.
- Ouvre `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` dans ton navigateur. Repère `"chat":{"id":123456789`. Ce nombre est ton secret `TELEGRAM_CHAT_ID`.

Tu peux activer les deux.

### 2. Crée une clé Twelve Data (recommandé)

- Crée un compte gratuit sur twelvedata.com et copie ta clé API.
- Le plan gratuit donne 800 crédits par jour. L'agent en utilise environ 160 par séance.
- Sans clé, l'agent utilise Yahoo Finance. Ça marche aussi, mais Yahoo bloque parfois les serveurs de GitHub. Avec une clé, Yahoo sert de secours automatique.

### 3. Crée le dépôt GitHub

- Sur github.com, clique sur **New repository**. Nom : `nvda-agent`. Choisis **Public**.
  - Public = minutes GitHub Actions illimitées et gratuites. Ton code est visible, tes secrets ne le sont jamais.
  - En privé, le quota gratuit (2 000 minutes par mois) ne suffit pas pour une passe toutes les 5 minutes.
- Clique sur **Add file > Upload files** et dépose `nvda_agent.py`, `requirements.txt` et `README.md`.
- Clique sur **Add file > Create new file**. Tape comme nom `.github/workflows/nvda-agent.yml`, colle le contenu du fichier `nvda-agent.yml`, puis valide.

### 4. Ajoute tes secrets

Dans le dépôt : **Settings > Secrets and variables > Actions > New repository secret**. Crée ceux dont tu as besoin :

- `NTFY_TOPIC`
- `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`
- `TWELVEDATA_API_KEY`

### 5. Teste

- Onglet **Actions**. Si GitHub le demande, active les workflows.
- Clique sur **Agent NVDA > Run workflow**, laisse le mode `test`, lance.
- Tu dois recevoir « Test agent NVDA » sur ton téléphone en moins d'une minute.
- Relance avec le mode `force` pour voir une vraie analyse, même marché fermé (le point d'ouverture n'arrive que pendant une séance).

C'est fini. L'agent tourne seul du lundi au vendredi pendant la séance US.

### Bon à savoir

- Séance US : 15h30 à 22h00 heure de Paris. Deux fois par an, pendant environ 2 semaines (mars et fin octobre), c'est 14h30 à 21h00. L'agent gère ces décalages tout seul.
- Aux heures chargées, GitHub peut lancer une passe avec quelques minutes de retard. L'agent rattrape les bougies manquées (jusqu'à 30 minutes).
- Si le dépôt n'a aucune activité pendant 60 jours, GitHub met les tâches planifiées en pause et t'envoie un mail. Un clic sur **Enable workflow** relance tout.
- Les jours fériés américains, aucune nouvelle bougie n'arrive, donc aucune alerte.

## Réglages

Dans **Settings > Secrets and variables > Actions > Variables**, tu peux créer :

| Variable | Défaut | Effet |
|---|---|---|
| `SEUIL_SCORE` | 5 | Score minimum pour alerter. Plus haut = moins d'alertes, plus sélectives. |
| `COOLDOWN_MIN` | 60 | Minutes minimum entre 2 alertes du même type. |
| `SEUIL_MOUVEMENT` | 2.5 | Variation en % sur 30 minutes pour l'alerte de mouvement brusque. |

Pour suivre une autre action, ajoute la variable `SYMBOL` (par exemple `AMD`) dans le bloc `env` du workflow.

## Utilisation sur ton PC (alternative)

Ton PC doit rester allumé pendant la séance US.

```bash
pip install -r requirements.txt

# Mac / Linux
export NTFY_TOPIC=nvda-z-7k2p9x4m
# Windows (invite de commandes)
set NTFY_TOPIC=nvda-z-7k2p9x4m

python nvda_agent.py --test       # notification de test
python nvda_agent.py --loop       # tourne toutes les 5 minutes
python nvda_agent.py --force      # une analyse tout de suite, même marché fermé
```

## Mesurer si les signaux marchent : le backtest

```bash
python nvda_agent.py --backtest
```

L'agent rejoue les 60 dernières séances avec les seuils 4, 5, 6 et 7. Pour chaque signal, il mesure si le cours est allé dans le bon sens 1 heure puis 1 séance plus tard. Il compare au hasard. Le détail des signaux part dans `signaux_backtest.csv`.

Lance-le une fois par mois. Si un seuil ne bat pas la référence « au hasard », ne te fie pas à ses alertes.

## Limites, à lire avant d'agir

- Aucun indicateur ne trouve le « meilleur moment » à coup sûr. L'agent repère des configurations qui ont un sens technique. Il ne connaît pas l'avenir.
- Les signaux techniques perdent leur valeur autour des résultats trimestriels de NVIDIA et des grandes annonces macro (Fed, inflation, restrictions d'export de puces). Vérifie l'actu avant chaque décision.
- Un signal d'achat dans une forte baisse peut arriver alors que la chute continue. Regarde la tendance de fond indiquée dans l'alerte.
- Le backtest ne compte ni les frais ni l'écart achat/vente. 60 séances, c'est court.
- Décide à l'avance combien tu peux perdre sur une position, et tiens-toi à ce montant.
