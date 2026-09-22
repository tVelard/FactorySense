# FactorySense — Prototype de surveillance IoT industrielle

Statut : validé pour implémentation
Périmètre : prototype technique uniquement (Docker Compose). Le contenu des slides n'est pas couvert par ce document.

## 1. Contexte et besoins

### Besoins métier
- Détecter une dérive d'équipement **avant** la panne, pas seulement au moment de la panne, pour donner à la maintenance une fenêtre d'action.
- Donner aux ingénieurs une vue d'ensemble en un coup d'œil du statut de chaque machine, pour prioriser les interventions.
- Tracer les alertes et leur traitement (qui a été notifié, quand acquittée) pour un argument de conformité/audit.
- Bénéfice attendu : réduction des arrêts non planifiés, donc des coûts associés.

### Besoins techniques
- Ingestion de télémétrie (vibration, température, pression) en continu, par machine.
- Détection de seuils dépassés (avertissement / critique) par capteur, sans spam (une alerte par franchissement de seuil, pas par point de mesure).
- Stockage : séries temporelles pour la télémétrie (immuable), état mutable pour les alertes (actif/acquittée).
- Dashboard unique affichant : statut global par machine, dernières valeurs brutes, courbes historiques, journal des alertes avec action d'acquittement.
- Communication frontend ↔ backend sans ambiguïté (le backend ne doit jamais être appelé directement par le navigateur).

## 2. Architecture

Quatre services Docker, un réseau commun :

```
sensor-simulator (Python) --HTTP POST /telemetry--> backend (FastAPI)
                                                          |
                                                          |--écrit--> InfluxDB (télémétrie)
                                                          |--écrit/lit--> SQLite (alertes, fichier local au conteneur)
                                                          |
                                          REST + WS amont  |
                                                          v
                                              frontend (Node/Express, BFF)
                                                          |
                                          REST + WS        |
                                                          v
                                                  navigateur (dashboard)
```

- Le navigateur ne parle qu'au frontend Node. Le frontend est un **BFF (Backend-For-Frontend)** : il relaie les appels REST vers FastAPI et maintient une unique connexion WebSocket amont vers le backend, qu'il rediffuse à tous les navigateurs connectés.
- Justification du choix InfluxDB + SQLite plutôt que "tout dans une seule base" : la télémétrie est un flux append-only à haut volume (bien adapté à une base temporelle) ; les alertes sont un état mutable à faible cardinalité (acquittement = simple `UPDATE`). Forcer les deux dans InfluxDB aurait demandé un modèle événementiel artificiel. SQLite reste un fichier embarqué dans le conteneur backend — ce n'est pas un service supplémentaire.

## 3. Services

### sensor-simulator (Python)
- Simule 3 machines. Chaque machine tourne dans sa propre boucle asynchrone, génère un point toutes les ~3s (bruit gaussien autour d'une baseline par capteur).
- Une machine a une fonction de dérive progressive (vibration et température qui montent lentement) pour illustrer la maintenance prédictive pendant la démo.
- `machine_id` dérivé du hostname du conteneur (`socket.gethostname()`) → pas de collision quand on scale ce service.
- POST vers `backend:8000/telemetry`. En cas d'échec (backend indisponible), log et on continue la boucle — jamais de crash.

### backend (FastAPI)
Endpoints :
- `POST /telemetry` — ingestion d'un point (écriture InfluxDB) + évaluation des seuils.
- `GET /machines` — liste des machines avec statut calculé (OK / Avertissement / Critique) et dernières valeurs brutes.
- `GET /telemetry/history?machine_id=&sensor=&range=` — série temporelle pour les courbes.
- `GET /alerts?status=active|acknowledged&machine_id=` — journal des alertes.
- `PATCH /alerts/{id}/acknowledge` — acquittement (statut + horodatage).
- `WS /ws/alerts` — push des nouvelles alertes et des acquittements.
- `GET /health` — pour le healthcheck Docker Compose.

Logique de seuils :
- Seuils warning/critical par type de capteur, définis dans un fichier de config chargé au démarrage (pas de CRUD admin, inutile pour un prototype).
- **Edge-triggered** : une nouvelle alerte n'est créée que lors du passage à une sévérité supérieure à l'état courant connu (en mémoire ou dernière alerte active en SQLite pour ce couple machine/capteur), jamais à chaque point au-dessus du seuil.

Résilience :
- Retry avec backoff sur la connexion InfluxDB au démarrage ; le conteneur n'est marqué "healthy" qu'une fois la connexion établie (`depends_on: condition: service_healthy` pour les services qui en dépendent).

### InfluxDB
- Measurement `telemetry` : champs vibration/temperature/pressure, tag `machine_id`.
- Authentification par token (pas d'accès anonyme), token injecté via variable d'environnement.

### frontend (Node/Express, BFF)
- Sert la page dashboard (rendu serveur via template, ex. EJS) avec l'état initial (machines + alertes actives) récupéré côté serveur au chargement.
- Routes proxy : `GET /api/history`, `POST /api/alerts/:id/ack` → relayées vers le backend.
- Une connexion WS amont vers `backend:8000/ws/alerts`, ouverte au démarrage avec reconnexion à backoff exponentiel si elle tombe ; rediffusée aux navigateurs connectés via une connexion WS côté frontend.
- Si le backend est injoignable : proxy REST renvoie 502 avec message clair, WS affiche un bandeau "reconnexion..." côté UI — jamais de crash du process Node.

## 4. Contenu du dashboard

Par machine :
- Badge de statut global (OK / Avertissement / Critique), dérivé du pire capteur.
- Dernières valeurs brutes (vibration, température, pression).
- Courbes historiques par capteur (à partir de `/telemetry/history`).
- Journal des alertes (actives + acquittées) avec bouton "Acquitter" sur les alertes actives.

Mise à jour live des alertes via le flux WebSocket relayé (pas de polling pour les alertes).

## 5. Tests

Un fichier `pytest` exécuté contre la stack `docker compose` déjà démarrée (pas de mocking) :
1. POST d'un point de télémétrie dans la plage normale → `GET /alerts` ne montre pas de nouvelle alerte.
2. POST d'un point au-dessus du seuil critique → une alerte `critical` apparaît dans `GET /alerts`.
3. `PATCH /alerts/{id}/acknowledge` → l'alerte passe en statut acquitté.

Commande documentée dans le README : `docker compose up -d && pytest tests/`.

## 6. Scalabilité (démonstration manuelle)

- `docker compose up --scale sensor-simulator=5` : chaque réplique génère un `machine_id` unique via son hostname de conteneur — aucune coordination nécessaire. Illustre l'ajout de machines dans l'usine et la capacité du backend/InfluxDB à absorber plus d'ingestion concurrente.
- Limite documentée dans le README : scaler le service `backend` lui-même n'est pas démontré ici (nécessiterait un load balancer devant, hors scope du prototype).

## 7. Sécurité (prototype)

- InfluxDB : authentification par token, pas d'accès anonyme.
- Secrets (token InfluxDB, etc.) injectés via fichier `.env` non committé (`.env.example` fourni).
- Le navigateur n'a jamais d'accès direct au backend ni à InfluxDB — seul le frontend Node y accède.
- Hors scope prototype (mentionné comme limite) : TLS entre services, authentification utilisateur sur le dashboard, chiffrement au repos.

## 8. Hors périmètre

- Authentification/autorisation utilisateur sur le dashboard.
- Notifications externes (email/SMS) sur alerte.
- Persistance de configuration des seuils via UI.
- Haute disponibilité / réplication des bases de données.
- Contenu des slides de présentation.
