{{ config(materialized='ephemeral') }}
-- Déduplication des séjours au grain du fait : une ligne par `stay_id`, dans sa
-- version la plus récente.
--
-- Modèle éphémère : dbt l'inline comme CTE dans `fact_sejour` et dans
-- `sejours_rejets`. Écrit une fois, il ne peut plus diverger entre les deux — c'était
-- un copier-coller dans la version SQL du pipeline.
--
-- Les alias de lignage ne reprennent pas le nom des colonnes source :
-- `max(_ingest_date) AS _ingest_date` rendrait les `argMax` voisins récursifs
-- (ILLEGAL_AGGREGATION).
SELECT
    stay_id,
    argMax(patient_pseudo, _ingest_date) AS patient_pseudo,
    argMax(service_code, _ingest_date)   AS service_code,
    argMax(admission_ts, _ingest_date)   AS admission_ts,
    argMax(discharge_ts, _ingest_date)   AS discharge_ts,
    argMax(admission_mode, _ingest_date) AS admission_mode,
    argMax(discharge_mode, _ingest_date) AS discharge_mode,
    argMax(_source_file, _ingest_date)   AS source_file,
    max(_ingest_date)                    AS last_ingest_date
FROM {{ source('bronze', 'sejours') }}
GROUP BY stay_id
