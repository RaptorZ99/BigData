-- Bases de l'entrepôt : une par couche du médaillon, plus les deux bases gold
-- séparées qui portent le cloisonnement des usages (pilotage / recherche).

CREATE DATABASE IF NOT EXISTS eds_bronze
    COMMENT 'Couche bronze : fichiers du lake typés, append-only, partitionnés par jour d''ingestion';

CREATE DATABASE IF NOT EXISTS eds_silver
    COMMENT 'Couche silver : constellation Kimball (3 faits + dimensions conformées), qualité tracée';

CREATE DATABASE IF NOT EXISTS eds_gold_pilotage
    COMMENT 'Couche gold — pilotage hospitalier : agrégats, aucune ligne patient';

CREATE DATABASE IF NOT EXISTS eds_gold_recherche
    COMMENT 'Couche gold — recherche clinique : agrégats k-anonymisés (k >= 5)';

CREATE DATABASE IF NOT EXISTS ops
    COMMENT 'Exploitation : journal d''ingestion, runs du pipeline, rapport qualité';
