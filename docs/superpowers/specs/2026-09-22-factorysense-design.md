# FactorySense — Prototype de surveillance IoT industrielle

Statut : implémenté (mis à jour le 2026-09-28 : PostgreSQL, load balancer nginx, backend scalable, authentification des capteurs)
Périmètre : prototype technique uniquement (Docker Compose). Le contenu des slides n'est pas couvert par ce document.

## 1. Contexte et besoins

### Besoins métier
- Détecter une dérive d'équipement **avant** la panne, pas seulement au moment de la panne, pour donner à la maintenance une fenêtre d'action.
- Donner aux ingénieurs une vue d'ensemble en un coup d'œil du statut de chaque machine, pour prioriser les interventions.
- Tracer les alertes et leur traitement (qui a été notifié, quand acquittée) pour un argument de conformité/audit.
- Bénéfice attendu : réduction des arrêts non planifiés, donc des coûts associés.

### Besoins techniques
- Ingestion de télémétrie (vibration, température, pression) en continu, par machine, depuis des capteurs authentifiés.
- Détection de seuils dépassés (avertissement / critique) par capteur, sans spam (une alerte par franchissement de seuil, pas par point de mesure).
- Stockage : séries temporelles pour la télémétrie (immuable), état mutable pour les alertes (actif/acquittée).
- Dashboard unique affichant : statut global par machine, dernières valeurs brutes, courbes historiques, journal des alertes avec action d'acquittement.
- Communication frontend ↔ backend sans ambiguïté (le backend ne doit jamais être appelé directement par le navigateur).
- Montée en charge horizontale des services applicatifs (`docker compose up --scale`).

## 2. Architecture

Six services Docker, un réseau commun :

```
sensor-simulator ×N ─POST /telemetry─┐
                                     ▼
 navigateur ──:3000──▶ lb (nginx) ──▶ frontend ×N ──REST + WS──▶ lb ──▶ backend ×N ──▶ InfluxDB (télémétrie)
                                                                          │    ▲
                                                               INSERT/UPDATE    │ NOTIFY 'alerts'
                                                                          ▼    │
                                                                   PostgreSQL (alertes)
```

| Service | État | Scalable |
|---|---|---|
| lb (nginx) | stateless | non (point d'entrée unique) |
| frontend (Node/Express, BFF) | stateless | oui |
| backend (FastAPI) | stateless | oui |
| sensor-simulator (Python) | stateless | oui |
| InfluxDB | stateful (volume `influxdb-data`) | non |
| PostgreSQL | stateful (volume `postgres-data`) | non |

- Le navigateur ne parle qu'au frontend Node, via le load balancer. Le frontend est un **BFF (Backend-For-Frontend)** : il relaie les appels REST vers FastAPI et maintient une unique connexion WebSocket amont vers le backend, qu'il rediffuse à tous les navigateurs connectés.
- Justification InfluxDB + PostgreSQL plutôt que « tout dans une seule base » : la télémétrie est un flux append-only à haut volume (bien adapté à une base temporelle) ; les alertes sont un état mutable à faible cardinalité (acquittement = simple `UPDATE`). Forcer les deux dans InfluxDB aurait demandé un modèle événementiel artificiel.
- Pourquoi PostgreSQL et plus SQLite (version initiale) : un fichier SQLite est local à un conteneur, ce qui empêchait de scaler le backend. PostgreSQL est partagé par toutes les répliques et fournit `LISTEN/NOTIFY` pour diffuser les alertes entre elles sans broker supplémentaire.

## 3. Services

### sensor-simulator (Python)
- Simule 3 machines par réplique. Chaque machine tourne dans sa propre boucle asynchrone et génère un point toutes les ~3 s (bruit gaussien autour d'une baseline par capteur).
- Une machine a une fonction de dérive progressive (vibration et température qui montent lentement, bornée) pour illustrer la maintenance prédictive pendant la démo.
- `machine_id` dérivé du hostname du conteneur (`socket.gethostname()`) → pas de collision quand on scale ce service.
- POST vers `lb:8000/telemetry` avec l'en-tête `X-API-Key`. En cas d'échec (backend indisponible), log et on continue la boucle — jamais de crash.

### backend (FastAPI)
Endpoints :
- `POST /telemetry` — authentifié par `X-API-Key` (`SENSOR_API_KEY`, comparaison à temps constant, 401 sinon) ; ingestion d'un point (écriture InfluxDB) + évaluation des seuils.
- `GET /machines` — liste des machines actives (10 dernières minutes) avec statut calculé (OK / Avertissement / Critique) et dernières valeurs brutes.
- `GET /telemetry/history?machine_id=&sensor=&range=` — série temporelle pour les courbes (paramètres validés par regex avant la requête Flux).
- `GET /alerts?status=active|acknowledged|superseded&machine_id=` — journal des alertes.
- `PATCH /alerts/{id}/acknowledge` — acquittement (statut + horodatage).
- `WS /ws/alerts` — push des nouvelles alertes et des acquittements.
- `GET /health` — pour le healthcheck Docker Compose.

Logique de seuils :
- Seuils warning/critical par type de capteur, définis dans `config.py` (pas de CRUD admin, inutile pour un prototype).
- **Edge-triggered** : une nouvelle alerte n'est créée que lors du passage à une sévérité supérieure à la dernière alerte active en base pour ce couple machine/capteur, jamais à chaque point au-dessus du seuil. L'escalade warning → critical marque l'alerte précédente `superseded`.
- Un index unique partiel PostgreSQL garantit au plus une alerte active par machine/capteur, même avec plusieurs répliques qui écrivent en parallèle.

Diffusion des alertes entre répliques :
- La création ou l'acquittement d'une alerte émet un `NOTIFY alerts` dans la même transaction (livré seulement au commit).
- Chaque réplique fait `LISTEN alerts` au démarrage (reconnexion automatique) et relaie chaque notification à ses propres clients WebSocket.

Résilience :
- Retry sur la connexion InfluxDB au démarrage ; le conteneur n'est marqué « healthy » qu'une fois la connexion établie (`depends_on: condition: service_healthy`).
- Pool de connexions PostgreSQL (`psycopg_pool`), qui rétablit les connexions perdues.
- `restart: unless-stopped` sur tous les services.

### InfluxDB
- Measurement `telemetry` : champs vibration/temperature/pressure, tag `machine_id`.
- Authentification par token (pas d'accès anonyme), token injecté via variable d'environnement. Non publié sur l'hôte.

### PostgreSQL
- Table `alerts` créée par `db/init.sql` au premier démarrage (volume vide).
- Identifiants injectés via `.env`. Publié uniquement sur `127.0.0.1:5432` (tests).

### lb (nginx)
- Résout `backend` et `frontend` via le DNS Docker à chaque requête (cache 5 s) : une adresse par réplique, répartition round-robin, nouvelles répliques prises en compte sans rechargement.
- Rejoue la requête sur une autre réplique si l'une refuse la connexion (`proxy_next_upstream`).
- Passe les WebSockets (en-têtes `Upgrade`, timeout long).
- Publie `3000` (dashboard) et `127.0.0.1:8000` (API, tests/débogage).

### frontend (Node/Express, BFF)
- Sert la page dashboard (rendu serveur EJS) avec l'état initial (machines + alertes actives) récupéré côté serveur au chargement.
- Routes proxy : `GET /api/machines`, `GET /api/history`, `POST /api/alerts/:id/ack` → relayées vers le backend via le load balancer.
- Une connexion WS amont vers `lb:8000/ws/alerts`, avec reconnexion à backoff exponentiel (remis à zéro à chaque connexion réussie) ; rediffusée aux navigateurs via une connexion WS côté frontend.
- Si le backend est injoignable : proxy REST renvoie 502, l'UI affiche « Reconnexion… » — jamais de crash du process Node.

## 4. Contenu du dashboard

Par machine :
- Badge de statut global (OK / Avertissement / Critique), dérivé du pire capteur.
- Dernières valeurs brutes (vibration, température, pression).
- Courbes historiques par capteur sur la dernière heure, avec seuils en pointillés.

Journal des alertes actives avec bouton « Acquitter ».

Mise à jour : alertes en direct via le WebSocket relayé ; valeurs, statuts et courbes rafraîchis toutes les 5 s (polling de `/api/machines`).

## 5. Tests

Exécutés contre la stack `docker compose` démarrée (pas de mocking) :
- `backend/tests/test_analysis.py`, `test_ws.py` — logique de seuils et diffusion WebSocket (unitaires).
- `backend/tests/test_alerts_db.py` — requêtes d'alertes sur le PostgreSQL de la stack, chaque test dans une transaction annulée.
- `backend/tests/test_alerts_api.py` — point normal → pas d'alerte ; point critique → alerte puis acquittement ; POST sans clé ou avec mauvaise clé → 401.
- `frontend/test/ws-relay.test.js` — une alerte créée côté backend arrive au navigateur via le BFF (avec plusieurs répliques : preuve du relais `LISTEN/NOTIFY`).

## 6. Scalabilité (démonstration manuelle)

- `docker compose up -d --scale backend=3 --scale frontend=2 --scale sensor-simulator=3`.
- Vérification : en-tête `X-Upstream` qui alterne entre répliques, logs `POST /telemetry` répartis sur chaque backend, 9 machines simulées, relais d'alerte réussi depuis chaque frontend.
- Non scalés : InfluxDB, PostgreSQL (stateful, une instance) et le load balancer. En production : réplication PostgreSQL, InfluxDB en cluster, load balancer redondant ou managé.

## 7. Sécurité (prototype)

- Capteurs authentifiés par clé API partagée (`X-API-Key`) sur l'ingestion.
- InfluxDB : authentification par token, pas d'accès anonyme, non exposé sur l'hôte.
- Secrets (token InfluxDB, identifiants PostgreSQL, clé capteur) injectés via `.env` non committé (`.env.example` fourni) ; Compose refuse de démarrer si une variable manque.
- Le navigateur n'a jamais d'accès direct au backend ni aux bases — seul le frontend Node y accède. Seul le port 3000 est exposé hors de la machine.
- Validation des entrées (Pydantic, regex anti-injection Flux, SQL paramétré).
- Hors scope prototype (mentionné comme limite) : TLS entre services, authentification utilisateur sur le dashboard, chiffrement au repos, clé par capteur (mTLS), token InfluxDB à moindre privilège.

## 8. Hors périmètre

- Authentification/autorisation utilisateur sur le dashboard.
- Notifications externes (email/SMS) sur alerte.
- Persistance de configuration des seuils via UI.
- Haute disponibilité / réplication des bases de données.
- Contenu des slides de présentation.
