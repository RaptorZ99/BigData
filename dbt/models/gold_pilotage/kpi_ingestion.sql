{{ config(order_by='(ingest_date, domaine)') }}
-- Journal d'ingestion exposé au métier : quel fichier, quel jour, combien de lignes.
--
-- `FINAL` force la fusion du ReplacingMergeTree : on lit l'état courant du journal,
-- pas l'historique de ses versions.
SELECT
    domain           AS domaine,
    ingest_date      AS ingest_date,
    source_file      AS fichier_source,
    rows_loaded      AS lignes_chargees,
    toString(status) AS statut,
    finished_at      AS traite_le
FROM {{ source('ops', 'ingest_log') }} FINAL
