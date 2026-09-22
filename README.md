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
cp .env.example .env
docker compose up -d --build
```

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
