-- Cloisonnement RGPD au niveau du moteur, pas seulement dans l'outil de dataviz.
--
-- Chaque usage a son propre compte SQL, en lecture seule, limité à SA base gold.
-- Conséquence : même une requête SQL écrite à la main dans Metabase par un
-- utilisateur « recherche » ne peut pas atteindre les données de pilotage — le
-- refus vient de ClickHouse. Les couches bronze, silver et ops ne sont exposées
-- à aucun des deux : elles restent réservées au compte technique du pipeline.
--
-- Script rejoué à chaque `eds provision-warehouse` : entièrement idempotent.

-- ── Pilotage hospitalier ────────────────────────────────────────────────────
CREATE USER IF NOT EXISTS chu_pilotage
    IDENTIFIED WITH sha256_password BY '{pilotage_password}'
    DEFAULT DATABASE eds_gold_pilotage;

GRANT SELECT ON eds_gold_pilotage.* TO chu_pilotage;
REVOKE ALL ON eds_bronze.*         FROM chu_pilotage;
REVOKE ALL ON eds_silver.*         FROM chu_pilotage;
REVOKE ALL ON eds_gold_recherche.* FROM chu_pilotage;
REVOKE ALL ON ops.*                FROM chu_pilotage;

-- ── Recherche clinique ──────────────────────────────────────────────────────
CREATE USER IF NOT EXISTS chu_recherche
    IDENTIFIED WITH sha256_password BY '{recherche_password}'
    DEFAULT DATABASE eds_gold_recherche;

GRANT SELECT ON eds_gold_recherche.* TO chu_recherche;
REVOKE ALL ON eds_bronze.*        FROM chu_recherche;
REVOKE ALL ON eds_silver.*        FROM chu_recherche;
REVOKE ALL ON eds_gold_pilotage.* FROM chu_recherche;
REVOKE ALL ON ops.*               FROM chu_recherche;
