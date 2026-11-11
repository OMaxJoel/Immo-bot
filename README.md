# 🏠 Assistant immobilier Abidjan — Gemini + Telegram (100 % gratuit)

Surveille des sites d'annonces, des flux RSS et des canaux Telegram publics, fait analyser chaque annonce par
Gemini, élimine les doublons et vous envoie sur Telegram les fiches (avec photos) des **2 pièces ≤ 150 000 FCFA**
à Riviera 2, Anono, Attoban, Blockhaus et Deux-Plateaux.

## Comment ça marche
```
sources (HTML / RSS / canaux Telegram publics)
   → pré-filtre gratuit (quartier + vocabulaire)  → Gemini (extraction JSON : prix, chambres, quartier…)
   → décision en Python (budget, 2 pièces, zone, ancienneté, prix suspect) → dédoublonnage SQLite
   → fiche Telegram + album photos
```
**Gemini extrait, le code décide** : aucun filtre ne dépend d'une réponse "libre" de l'IA, et le prompt interdit
d'inventer. Une annonce n'est jamais présentée comme disponible : la mention « À confirmer » est systématique.

## Mise en route (≈ 15 min)
1. **Bot Telegram** : sur Telegram, parlez à `@BotFather` → `/newbot` → copiez le **token**.
2. **Clé Gemini gratuite** : https://aistudio.google.com/apikey (sans carte bancaire).
3. **GitHub** : créez un dépôt **public** (minutes Actions illimitées), poussez ce dossier.
   Settings → Secrets and variables → Actions → ajoutez `GEMINI_API_KEY` et `TELEGRAM_BOT_TOKEN`.
4. **Chat ID** : lancez une fois en local (voir plus bas) puis envoyez `/start` à votre bot : il vous répond avec
   votre `TELEGRAM_CHAT_ID`. Ajoutez-le aussi dans les secrets. *(Tant qu'il n'est pas défini, le bot ne parle à personne ;
   une fois défini, il ignore tout autre utilisateur.)*
5. **Vérifiez les sources** (étape la plus importante, voir ci-dessous), puis onglet *Actions* → *Veille immobilière* → *Run workflow*.

### Test local
```bash
pip install -r requirements.txt
cp .env.example .env   # remplir, puis : export $(grep -v '^#' .env | xargs)
python -m src.main --check-sources   # teste la collecte, sans Gemini ni Telegram
python -m src.main --once            # un passage complet
```

## ⚠️ Configurer les sources (config.yaml)
Je n'ai pas pu vérifier la structure de chaque site : les URL fournies sont des **points de départ**. Pour chaque site,
ouvrez la page de résultats déjà filtrée (location → appartement → Cocody…), copiez son URL dans `config.yaml`, ajoutez
si besoin `link_regex` (motif des liens d'annonces), puis lancez `python -m src.main --check-sources`.
`OK` = des liens d'annonces sont trouvés ; `KO` = à corriger ou site non accessible (robots.txt, protection anti-bot, site rendu en JavaScript).

## Ce qui est possible… et ce qui ne l'est pas (honnêtement)
| Source | Statut |
|---|---|
| Sites d'annonces et d'agences | ✅ pages publiques, robots.txt respecté. Les sites 100 % JavaScript ou protégés (Cloudflare) peuvent bloquer l'IP de GitHub. |
| Canaux Telegram publics | ✅ via `t.me/s/<canal>` (ajoutez les vôtres dans `config.yaml`) |
| Flux RSS | ✅ ex. **Google Alerts** (alertes sur « appartement 2 pièces Riviera » → flux RSS) : gratuit, légal, et capte des pages indexées dont certaines publications publiques. |
| **Facebook** (Marketplace, groupes), Instagram, TikTok | ❌ pas de collecte automatique : conditions d'utilisation interdites et contenu derrière connexion. **Alternative conforme** : *transférez ou collez* l'annonce (texte, capture, lien) à votre bot, il l'analyse et répond. Astuce : activez les notifications de vos groupes Facebook et transférez ce qui vous intéresse en 2 secondes. |
| Airbnb / Booking | ❌ non inclus : API payante ou scraping interdit, et tarifs journaliers hors budget 150 000 FCFA/mois. Les annonces courte durée détectées ailleurs sont écartées. |
| Disponibilité | ⚠️ seulement détection des pages supprimées/expirées. La confirmation reste à faire auprès du propriétaire. |
| Groupes privés, groupes d'agences fermés | ❌ non accessibles |

## Limites techniques à connaître
- **GitHub Actions** : le cron `*/30` est « au mieux » (retards de plusieurs minutes fréquents). Les commandes Telegram sont lues à chaque
  passage → réponse sous ~30 min. Pour des réponses **instantanées**, lancez `python -m src.main --daemon` sur un PC, un Raspberry ou un
  serveur gratuit (ex. offre gratuite Oracle Cloud, qui demande toutefois une carte pour vérification).
- GitHub désactive les workflows planifiés d'un dépôt public après 60 jours sans activité : faites un petit commit de temps en temps.
- **Quota Gemini gratuit** : limité (requêtes/min et /jour, variables selon le modèle). Le pré-filtre, le plafond `max_calls_per_run` et la pause entre appels
  protègent le quota. Vérifiez le modèle dans `config.yaml`. En cas de dépassement, le scan s'arrête proprement et reprend au passage suivant.
- Au premier passage, l'historique de chaque site est examiné (annonces anciennes signalées comme telles).
- Une annonce déjà vue n'est pas renvoyée si elle est simplement « remontée » (actualisée) ; seule une nouvelle URL ou une nouvelle empreinte déclenche une alerte.
- Un « démarcheur » est signalé seulement si l'annonce permet de le déduire. Les prix très bas sont signalés comme suspects.
- Le bot ne contacte jamais un propriétaire et ne paie rien.

## Sécurité
Token et clés uniquement dans les *secrets* GitHub / variables d'environnement (jamais dans le code). Les erreurs Telegram sont
masquées pour ne pas afficher le token dans les logs. Le bot n'obéit qu'à votre `TELEGRAM_CHAT_ID`.
La base SQLite est dans le cache GitHub (non publique), pas dans le dépôt.

## Commandes Telegram
`/start` `/recherche` `/criteres` `/sources` `/recentes` `/budget [150000|150k]` `/localisation [Riviera 2, Blockhaus]` `/stop` `/resume`
