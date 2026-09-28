# FactorySense — Prototype de surveillance IoT industrielle

Prototype Docker Compose : simulateur de capteurs → load balancer nginx → backend FastAPI (InfluxDB + PostgreSQL) → dashboard Node.js.
Conception complète : `docs/superpowers/specs/2026-09-22-factorysense-design.md`.

## Services

| Service | Rôle | État | Scalable | Port host |
|---|---|---|---|---|
| lb | nginx : load balancer devant `backend` et `frontend` | stateless | non (point d'entrée unique) | 3000, `127.0.0.1:8000` |
| frontend | Dashboard Node/Express (BFF), relaie REST + WebSocket vers le backend | stateless | oui | — |
| backend | API FastAPI, détection de seuils, alertes, WebSocket | stateless | oui | — |
| sensor-simulator | Génère 3 machines simulées, une en dérive progressive | stateless | oui | — |
| influxdb | Séries temporelles (télémétrie) | stateful | non | — |
| postgres | Alertes (état mutable) + diffusion des alertes entre répliques (`LISTEN/NOTIFY`) | stateful | non | `127.0.0.1:5432` (tests) |

```
sensor-simulator ×N ─POST /telemetry─┐
                                     ▼
 navigateur ──:3000──▶ lb (nginx) ──▶ frontend ×N ──REST + WS──▶ lb ──▶ backend ×N ──▶ InfluxDB
                                                                          │    ▲
                                                               INSERT/UPDATE    │ NOTIFY 'alerts'
                                                                          ▼    │
                                                                        PostgreSQL
```

## Démarrage

```bash
cp .env.example .env   # identifiants InfluxDB, PostgreSQL, clé capteur : à personnaliser
docker compose up -d --build
```

`docker compose up` démarre toute la stack, simulation comprise. Sans `.env`, Compose s'arrête avec un message explicite.

Dashboard : http://localhost:3000

## Tests

```bash
# charger le .env dans le shell (clé capteur + identifiants PostgreSQL pour les tests)
set -a; . ./.env; set +a

# unitaires + intégration backend (nécessite la stack lancée ; les tests de la base
# s'exécutent sur le PostgreSQL de la stack, dans une transaction annulée à la fin)
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -v

# relais WebSocket frontend (nécessite la stack lancée)
docker compose exec -e BACKEND_URL=http://lb:8000 -e SENSOR_API_KEY frontend node test/ws-relay.test.js
```

## Scalabilité

Les trois services stateless (`backend`, `frontend`, `sensor-simulator`) se scalent indépendamment, à chaud, sans redémarrer le reste :

```bash
docker compose up -d --scale backend=3 --scale frontend=2 --scale sensor-simulator=3
```

### Comment ça marche

1. **Découverte des répliques.** Docker Compose donne à chaque réplique un conteneur distinct (`backend-1`, `backend-2`…). Le DNS interne de Docker (`127.0.0.11`) répond au nom `backend` avec **une adresse IP par réplique**.
2. **Répartition de charge.** nginx (`lb/nginx.conf`) résout `backend` et `frontend` au moment de la requête (cache de 5 s) et répartit en round-robin sur toutes les adresses. Une réplique ajoutée est donc prise en compte en moins de 5 s, sans recharger nginx. Si une réplique refuse la connexion (en démarrage ou en arrêt), nginx rejoue la requête sur la suivante (`proxy_next_upstream`).
3. **État partagé.** Aucune réplique ne garde d'état local : la télémétrie va dans InfluxDB et les alertes dans PostgreSQL. N'importe quelle réplique peut donc traiter n'importe quelle requête. Un index unique partiel garantit au plus une alerte active par machine et par capteur, même avec plusieurs répliques qui écrivent en même temps.
4. **Diffusion des alertes entre répliques.** Chaque frontend garde une connexion WebSocket vers **une** réplique backend, alors qu'une alerte peut être créée par une autre. Le backend qui crée ou acquitte une alerte envoie donc un `NOTIFY alerts` dans la même transaction. Chaque réplique fait `LISTEN alerts` et relaie à ses propres clients WebSocket. Tous les navigateurs reçoivent ainsi toutes les alertes, quelle que soit la réplique qui les a produites.
5. **Simulateurs.** Chaque réplique génère 3 machines avec un `machine_id` dérivé du hostname du conteneur : pas de collision, et la charge d'ingestion croît avec le nombre de répliques.

### Vérifier

```bash
docker compose ps                        # 3 backend, 2 frontend, 3 sensor-simulator

# le load balancer alterne entre les répliques (en-tête X-Upstream = IP de la réplique)
for i in $(seq 9); do curl -sI localhost:8000/health | grep -i x-upstream; done | sort | uniq -c

# chaque réplique backend reçoit une part de la télémétrie
docker compose logs --since 20s backend | grep 'POST /telemetry' | awk '{print $1}' | sort | uniq -c

# 9 machines simulées (3 par réplique de simulateur)
curl -s localhost:8000/machines | python3 -m json.tool

# une alerte créée sur une réplique arrive sur chaque frontend (relancer plusieurs fois)
set -a; . ./.env; set +a
docker compose exec --index 2 -e BACKEND_URL=http://lb:8000 -e SENSOR_API_KEY frontend node test/ws-relay.test.js
```

Revenir à l'état initial (les requêtes en cours basculent sur les répliques restantes) :

```bash
docker compose up -d --scale backend=1 --scale frontend=1 --scale sensor-simulator=1
```

**Ce qui ne se scale pas ici** : InfluxDB et PostgreSQL (stateful, une instance chacun), et le load balancer (point d'entrée unique). En production, on utiliserait une réplication PostgreSQL primaire/réplicas, InfluxDB en cluster (Enterprise ou Cloud) et deux load balancers avec une IP flottante (keepalived) ou un load balancer managé.

## Sécurité et résilience

- **Authentification des capteurs** : `POST /telemetry` exige l'en-tête `X-API-Key`, qui doit correspondre à `SENSOR_API_KEY` (défini dans `.env`, comparaison à temps constant). Sans cette clé, la réponse est `401`, ce qui empêche l'injection de fausses mesures. Pour tester : `curl -i -X POST localhost:8000/telemetry -H 'Content-Type: application/json' -d '{}'`.
- **Surface réseau minimale** : seul le dashboard (port 3000, via le load balancer) est exposé. InfluxDB n'est joignable que depuis le réseau Docker interne. L'API (`127.0.0.1:8000`) et PostgreSQL (`127.0.0.1:5432`) ne sont publiés que sur la boucle locale, pour les tests et le débogage.
- **Secrets hors du code** : identifiants InfluxDB et PostgreSQL et clé capteur dans `.env` (non versionné). Compose refuse de démarrer si une variable manque.
- **Redémarrage automatique** : `restart: unless-stopped` sur tous les services. Un conteneur qui plante est relancé. Le frontend se reconnecte au WebSocket du backend avec un backoff exponentiel, et le backend rétablit son `LISTEN` PostgreSQL. Avec plusieurs répliques, la perte de l'une d'elles est absorbée par le load balancer.
- **Validation des entrées** : schéma Pydantic sur la télémétrie, regex sur `machine_id`, `sensor` et `range` avant toute requête Flux (anti-injection), SQL paramétré.

## Limites connues

- Pas d'authentification utilisateur sur le dashboard (hors périmètre du prototype).
- La clé capteur est partagée par tous les simulateurs : une clé compromise permet d'usurper n'importe quelle machine. En production : un certificat ou une clé par capteur (mTLS).
- InfluxDB, PostgreSQL et le load balancer restent des instances uniques (voir « Scalabilité »).
- Une alerte émise pendant qu'un frontend se reconnecte au WebSocket du backend (redémarrage d'une réplique) n'est pas rejouée : elle apparaît au prochain rechargement de la page.
- Pas de TLS entre services, pas de chiffrement au repos (hors scope prototype, voir la spec section 7).
- Une alerte reste active jusqu'à acquittement manuel, même si la mesure revient à la normale (choix assumé pour la traçabilité).
- Le dashboard rafraîchit valeurs, statuts et courbes toutes les 5 s (polling), et les alertes arrivent en direct par WebSocket. Une machine apparue après le chargement de la page (par exemple après un `--scale`) ne s'affiche qu'au rechargement.
- Une panne d'InfluxDB désactive silencieusement la génération d'alertes (l'écriture de télémétrie échoue avant l'évaluation des seuils).
- Dans chaque réplique, l'écriture InfluxDB et les accès PostgreSQL de l'ingestion sont synchrones sur la boucle d'événements FastAPI. On scale donc en ajoutant des répliques plutôt qu'en parallélisant à l'intérieur d'une réplique.
- `GET /health` ne vérifie la disponibilité d'InfluxDB qu'au démarrage, jamais ensuite.
- Le token InfluxDB utilisé par le backend a les droits admin (pas de moindre privilège) — à restreindre dans un vrai déploiement.
- Le badge d'une machine reflète ses dernières mesures, tandis que le journal garde l'alerte jusqu'à son acquittement : une machine revenue à la normale peut donc afficher « Normal » avec une alerte encore active.

## Choix techniques

Tous les composants sont open-source et intégrés plutôt que recodés.

| Besoin | Outil | Pourquoi | Alternative écartée |
|---|---|---|---|
| Stocker la télémétrie | **InfluxDB 2.7** (MIT) | Base temporelle : écriture append-only à haut débit, requêtes par fenêtre de temps (`range`, `last`) natives en Flux, rétention configurable par bucket | PostgreSQL : il faudrait gérer soi-même l'indexation temporelle et la purge (ou ajouter TimescaleDB) |
| Stocker les alertes | **PostgreSQL 16** | Les alertes sont un état mutable (actif → acquitté = un `UPDATE`) ; InfluxDB est pensé pour des points immuables. Base partagée par toutes les répliques backend, contrainte d'unicité côté base, et `LISTEN/NOTIFY` qui diffuse les alertes entre répliques sans broker supplémentaire | SQLite : fichier local à un conteneur, empêche de scaler le backend. Redis pub/sub : un service de plus alors que PostgreSQL fait déjà le travail |
| Répartition de charge | **nginx** | Load balancer éprouvé, découvre les répliques par le DNS Docker à chaque requête (pas de rechargement au `--scale`), gère le passage des WebSockets et le rejeu sur une autre réplique | Traefik : découverte automatique, mais exige de monter le socket Docker dans un conteneur (risque de sécurité). HAProxy : équivalent, configuration moins courante |
| API + détection d'anomalies | **FastAPI** (Python) | Validation des entrées par Pydantic (rejet des payloads mal formés), WebSocket natif pour pousser les alertes, client InfluxDB officiel en Python, doc OpenAPI auto sur `/docs` | Express : pas de validation de schéma intégrée |
| Dashboard | **Node/Express + EJS** en BFF, **Chart.js** | Le navigateur ne parle qu'au frontend, jamais au backend ni à la base : une seule surface exposée. Le BFF garde **une** connexion WebSocket vers le backend et la rediffuse à N navigateurs. Rendu serveur (EJS) : pas de build front | Grafana : rapide mais « vanilla », sans acquittement d'alertes ni personnalisation métier. SPA React : chaîne de build inutile pour un seul écran |
| Temps réel | **WebSocket** | Une alerte doit apparaître sans attendre un cycle de polling | Polling : latence + requêtes à vide |
| Simulation | **Script Python asyncio + httpx** | Une coroutine par machine, une machine dérive progressivement pour démontrer la détection *avant* la panne. `machine_id` dérivé du hostname : `--scale` sans collision | — |
| Orchestration | **Docker Compose** | Healthchecks + `depends_on: service_healthy` : chaque service attend que sa dépendance soit prête, la stack démarre en une commande | — |

Personnalisation (au-delà des configurations par défaut) : seuils warning/critical par capteur, dédoublonnage des alertes (une alerte par franchissement, escalade warning → critical), acquittement tracé (horodatage), validation anti-injection des requêtes Flux.

## Consigne

Contexte du Projet

Une entreprise de fabrication souhaite surveiller ses équipements de production en temps réel pour éviter les temps d'arrêt coûteux.
Le système doit :

    Collecter et traiter les données de télémétrie (vibrations, température, pression).
    Générer des alertes en temps réel pour les anomalies (ex. : surchauffe, vibrations inhabituelles).
    Fournir aux ingénieurs un tableau de bord affichant les données historiques et les alertes en direct.

Livrables (Présentation + Prototype)

1. Présentation (5 diapositives, PDF uniquement)

    Diapositive 0 : Membres du groupe (noms).
    Diapositive 1 : Besoins Métier
        Quels sont les objectifs pour les ingénieurs et les équipes de maintenance ?
        Quels sont les bénéfices attendus (réduction des temps d'arrêt, économies, conformité) ?
    Diapositive 2 : Besoins Techniques
        Quels services doivent être développés ?
        Quelles données doivent être stockées et sécurisées ?
    Diapositive 3 : Architecture Proposée
        Modèle de déploiement de l'infra (Cloud privé, cloud publique, ...), modèle de service (IaaS, PaaS)
        Prototype d'application multi-container basée sur Docker.
    Diapositive 4 : Analyse des Risques et Atténuation
        Menaces principales (ex. : fuites de données, pannes de capteurs).
        Contre-mesures (chiffrement, authentification, redondance).

2. Mini-Prototype (Docker Compose)

    Doit inclure au moins 3 services (ex. : frontend, backend, base de données, analyse, ...).
    Utiliser des composants open-source : pas besoin de coder from scratch, votre tâche est de les intégrer.
    Doit effectuer au moins une opération principale du système (ex. : simuler des données de capteurs, déclencher des alertes).

Contraintes :

    Les services doivent communiquer (ex. : frontend ↔ backend ↔ base de données).
    Stocker et afficher des données de télémétrie simulées.
    Tester la scalabilité manuellement (ex. : docker compose up --scale).
    Documenter le fonctionnement et les limites dans un README.
Critères de Validation

Vous serez évalué sur :

    Présentation (60%)
        Schéma d'architecture clair.
        Distinction explicite entre les besoins métier et techniques.
        Analyse de sécurité (menaces + atténuation)
        Questions individuelles

    Fonctionnalités (20%)

        Docker Compose exécute tous les services.
        Le frontend se connecte au backend.
        README avec instructions de configuration.

    Esthétique (20%)
        Qualité du code et de l'intégration.
        Personnalisation (éviter les configurations "vanilla").
        Justification des choix d'outils.
Exemples pour la Présentation et le Prototype

Besoins Métier :

    Que doivent obtenir les ingénieurs ? (ex. : alertes en temps réel, tendances historiques).
    Quels sont les bénéfices ? (ex. : maintenance proactive, efficacité).

Besoins Techniques :

    Quels services sont nécessaires ? (ex. : ingestion de données, alertes, visualisation).
    Quelles données doivent être sécurisées ? (ex. : journaux de capteurs, registres de maintenance).

Architecture :

    Schéma avec services, flux de données et dépendances.
    Identifier les composants stateful (ex. : base de données) et stateless (ex. : API).

Analyse de Sécurité :

    Menaces : Altération des données, accès non autorisé, usurpation de capteurs.
    Atténuation : TLS, accès basé sur les rôles, détection des anomalies.
Exemple d'outils open source pour le prototype (Docker Compose) :

    Frontend : Tableau de bord (ex. : Flask/Node.js).
    Backend : API (ex. : FastAPI/Express).
    Base de données : Base de données temporelle (ex. : InfluxDB) ou PostgreSQL.
    Analyse : Script Python pour simuler des données et déclencher des alertes.
    Tests : Vérifier les alertes à partir de données fictives.
    Scalabilité : Tester avec docker compose up --scale.
    Documentation : README avec configuration, utilisation et limites.
