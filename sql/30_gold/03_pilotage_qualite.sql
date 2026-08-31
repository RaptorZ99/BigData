-- Gold pilotage — le rapport qualité, exposé aux utilisateurs métier.
--
-- Rendre visible ce qui a été écarté et pourquoi, c'est ce qui permet de
-- répondre à « d'où sort ce chiffre ? » depuis le dashboard lui-même, sans
-- ouvrir la base d'exploitation (à laquelle le compte pilotage n'a pas accès).
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_qualite_pipeline
ENGINE = MergeTree
ORDER BY (rule)
COMMENT 'Contrôles qualité du dernier run : lignes lues, conservées, écartées'
AS
SELECT
    q.layer         AS couche,
    q.table_name    AS table_cible,
    q.rule          AS rule,
    q.rule_label    AS controle,
    -- Nature de la règle : ce qu'il faut lire dans les compteurs.
    multiIf(
        q.rows_rejected > 0, 'rejet',
        q.rows_flagged  > 0, 'signalement',
        'contrôle conforme'
    )               AS nature,
    q.rows_in       AS lignes_lues,
    q.rows_kept     AS lignes_conservees,
    q.rows_rejected AS lignes_ecartees,
    q.rows_flagged  AS lignes_signalees,
    q.details       AS precisions,
    q.checked_at    AS controle_le
FROM ops.quality_report AS q
WHERE q.run_id = '{run_id}';

-- Journal d'ingestion exposé : quel fichier, quel jour, combien de lignes.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_ingestion
ENGINE = MergeTree
ORDER BY (ingest_date, domaine)
COMMENT 'Traçabilité de l''ingestion : fichier source, jour, volumétrie, statut'
AS
SELECT
    domain      AS domaine,
    ingest_date AS ingest_date,
    source_file AS fichier_source,
    rows_loaded AS lignes_chargees,
    toString(status) AS statut,
    finished_at AS traite_le
FROM ops.ingest_log FINAL;
