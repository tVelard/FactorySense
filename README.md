# FactorySense — Surveillance IoT industrielle

Prototype Docker Compose qui surveille des machines en temps réel : des capteurs simulés envoient vibration, température et pression, le backend détecte les dépassements de seuil et le dashboard affiche les mesures et les alertes en direct.

| Service | Rôle | Scalable |
|---|---|---|
| `load-balancer` | nginx, point d'entrée unique, répartit la charge sur `frontend` et `backend` | non |
| `frontend` | Dashboard Node/Express : mesures, courbes, alertes en direct | oui |
| `backend` | API FastAPI : ingestion, détection des seuils, alertes, WebSocket | oui |
| `sensor-simulator` | Simule 3 machines, dont une qui dérive progressivement | oui |
| `telemetry-db` | InfluxDB : stocke la télémétrie (séries temporelles) | non |
| `alerts-db` | PostgreSQL : stocke les alertes, partagées par toutes les répliques du backend | non |

## Démarrage

Prérequis : Docker Desktop lancé.

```bash
cp .env.example .env         
docker compose up -d --build
```

- Dashboard : http://localhost:3000
- API et documentation interactive : http://localhost:8000/docs (accessible depuis la machine locale uniquement)

Arrêter : `docker compose down`. Pour effacer aussi les données : `docker compose down -v`.

## Tests

La stack doit être lancée.

```bash
set -a; . ./.env; set +a      # charge les variables du .env dans le shell

# backend
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -v
cd ..

# relais WebSocket du frontend
docker compose exec -e BACKEND_URL=http://load-balancer:8000 -e SENSOR_API_KEY frontend node test/ws-relay.test.js
```

## Scalabilité

```bash
docker compose up -d --scale backend=3 --scale frontend=2 --scale sensor-simulator=3
```

- nginx découvre automatiquement les nouvelles répliques via le DNS de Docker et répartit les requêtes entre elles.
- Le backend ne garde aucun état local : les mesures sont dans InfluxDB et les alertes dans PostgreSQL, donc n'importe quelle réplique peut traiter n'importe quelle requête.
- Une alerte créée par une réplique est diffusée à toutes les autres par `LISTEN/NOTIFY` de PostgreSQL, pour que chaque dashboard la reçoive.

Vérifier que la charge est répartie (l'en-tête `X-Upstream` donne l'IP de la réplique qui a répondu) :

```bash
for i in $(seq 9); do curl -sI localhost:8000/health | grep -i x-upstream; done | sort | uniq -c
```

Revenir à une seule réplique : `docker compose up -d --scale backend=1 --scale frontend=1 --scale sensor-simulator=1`

## Sécurité

- **Capteurs authentifiés** : `POST /telemetry` exige l'en-tête `X-API-Key`, sinon il répond `401`.
- **Surface réseau réduite** : seul le port 3000 est exposé. L'API (8000) et PostgreSQL (5432) n'écoutent que sur `127.0.0.1`, et InfluxDB n'est pas exposé.
- **Secrets hors du code** : ils sont dans `.env`, qui n'est pas versionné. Compose refuse de démarrer s'il manque une variable.
- **Entrées validées** : schéma Pydantic, regex sur les paramètres des requêtes InfluxDB (anti-injection), SQL paramétré.

## Choix techniques

| Besoin | Outil | Pourquoi |
|---|---|---|
| Télémétrie | InfluxDB | Base temporelle, faite pour écrire beaucoup de points et interroger par période |
| Alertes | PostgreSQL | Les alertes changent d'état (active → acquittée) ; base partagée entre répliques |
| Répartition de charge | nginx | Suit le `--scale` sans redémarrage et gère les WebSockets |
| API | FastAPI | Validation des entrées intégrée, WebSocket natif, doc auto sur `/docs` |
| Dashboard | Node/Express + Chart.js | Le navigateur ne parle qu'au frontend, jamais directement au backend |
| Orchestration | Docker Compose | Healthchecks : chaque service attend que ses dépendances soient prêtes |

## Limites connues

- Pas d'authentification sur le dashboard, et une seule clé API partagée par tous les capteurs.
- Pas de TLS entre les services ni de chiffrement des données au repos.
- InfluxDB, PostgreSQL et nginx restent des instances uniques.
- Une alerte reste active jusqu'à son acquittement manuel, même si la mesure revient à la normale.
- Une machine apparue après le chargement de la page n'est affichée qu'au rechargement.
- Si InfluxDB tombe après le démarrage, les mesures sont refusées et plus aucune alerte n'est générée.

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `backend/`, `frontend/`, `sensor-simulator/` | Code des services |
| `load-balancer/` | Configuration nginx du load balancer |
| `alerts-db/` | Schéma PostgreSQL des alertes, appliqué au premier démarrage |
| `presentation/` | Slides de soutenance (PDF, PPTX, HTML) |
| `docs/` | [Consigne du projet](docs/consigne.md) et spécification de conception |
