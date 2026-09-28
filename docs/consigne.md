# Consigne

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
