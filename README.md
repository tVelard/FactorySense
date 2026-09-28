# FactorySense — Prototype de surveillance IoT industrielle

Prototype Docker Compose : simulateur de capteurs → backend FastAPI (InfluxDB + SQLite) → dashboard Node.js.
Conception complète : `docs/superpowers/specs/2026-09-22-factorysense-design.md`.

## Services

| Service | Rôle | Port host |
|---|---|---|
| influxdb | Stockage des séries temporelles (télémétrie) | 8086 |
| backend | API FastAPI, détection de seuils, alertes (SQLite), WebSocket | 8000 |
| sensor-simulator | Génère 3 machines simulées, une en dérive progressive | — |
| frontend | Dashboard Node/Express (BFF), relaie REST + WebSocket vers le backend | 3000 |

## Démarrage

```bash
cp .env.example .env   # identifiants InfluxDB, à personnaliser
docker compose up -d --build
```

`docker compose up` démarre toute la stack, simulation comprise. Sans `.env`, Compose s'arrête avec un message explicite.

Dashboard : http://localhost:3000

## Tests

```bash
# unitaires + intégration backend (nécessite la stack lancée)
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -v

# relais WebSocket frontend (nécessite la stack lancée)
docker compose exec -e BACKEND_URL=http://backend:8000 frontend node test/ws-relay.test.js
```

## Scalabilité

```bash
docker compose up -d --scale sensor-simulator=3
```

Chaque réplique du simulateur génère 3 machines avec un `machine_id` unique dérivé du hostname du conteneur — aucune collision. Vérifier :

```bash
curl -s http://localhost:8000/machines | python3 -m json.tool
```

Revenir à l'état initial :

```bash
docker compose up -d --scale sensor-simulator=1
```

## Limites connues

- Le port 8000 du backend est publié côté host uniquement pour les tests automatisés et le débogage ; dans un vrai déploiement il ne serait pas exposé directement.
- Pas d'authentification utilisateur sur le dashboard (hors périmètre du prototype).
- Scaler le service `backend` n'est pas démontré (nécessiterait un load balancer devant, hors scope).
- Pas de TLS entre services, pas de chiffrement au repos (hors scope prototype, voir la spec section 7).
- Une alerte reste active jusqu'à acquittement manuel, même si la mesure revient à la normale (choix assumé pour la traçabilité).
- Les valeurs affichées sur le dashboard et les courbes historiques sont chargées une seule fois au chargement de la page (pas de rafraîchissement automatique) — recharger la page pour voir les données à jour.
- Une panne d'InfluxDB désactive silencieusement la génération d'alertes (l'écriture de télémétrie échoue avant l'évaluation des seuils).
- L'ingestion et les accès SQLite sont synchrones sur la boucle d'événements FastAPI — suffisant à l'échelle de la démo, mais ne parallélise pas réellement l'ingestion.
- `GET /health` ne vérifie la disponibilité d'InfluxDB qu'au démarrage, jamais ensuite.
- Le token InfluxDB utilisé par le backend a les droits admin (pas de moindre privilège) — à restreindre dans un vrai déploiement.
- Le statut affiché sur la carte d'une machine (badge) peut diverger brièvement du journal des alertes tant qu'une alerte active n'a pas été acquittée.
