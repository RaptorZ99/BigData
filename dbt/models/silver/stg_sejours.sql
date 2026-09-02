{{ config(materialized='ephemeral') }}
-- Référentiel des séjours déposés : une ligne par `stay_id`, dans sa version la plus
-- récente, avec le verdict du contrôle de cohérence temporelle.
--
-- Modèle éphémère : dbt l'inline comme CTE partout où il est référencé. Écrit une
-- seule fois, la déduplication ne peut plus diverger d'un modèle à l'autre.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  Pourquoi un référentiel de TOUS les séjours, et pas seulement `fact_sejour`
--
--  Le contrôle Q2 (`discharge_ts` < `admission_ts`) invalide **les horodatages** du
--  séjour, pas le séjour lui-même : le patient existe, le service existe, les
--  diagnostics codés pendant ce séjour sont des faits cliniques, et les constantes
--  relevées au chevet portent leur propre horodatage.
--
--  Écarter en cascade tout ce qui s'y rattache reviendrait à faire disparaître une
--  infection urinaire parce qu'une date de sortie a été mal saisie. Le coût mesuré
--  de cette cascade : quinze patients manquants sur la prévalence de N39, et
--  528 relevés valides perdus sur 41 778.
--
--  Règle retenue : **un rejet ne vaut que pour la table où vit l'anomalie.**
--  `fact_sejour` écarte les séjours incohérents — leurs durées sont inexploitables.
--  `fact_diagnostic` et `fact_monitoring` résolvent leur patient et leur service
--  depuis ce référentiel, qui les contient tous.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Les alias de lignage ne reprennent pas le nom des colonnes source :
-- `max(_ingest_date) AS _ingest_date` rendrait les `argMax` voisins récursifs
-- (ILLEGAL_AGGREGATION).
SELECT
    stay_id,
    patient_pseudo,
    service_code,
    admission_ts,
    discharge_ts,
    admission_mode,
    discharge_mode,

    -- Q2 — le seul contrôle qui écarte un séjour.
    -- Une sortie non renseignée n'est pas une anomalie : le patient est encore
    -- hospitalisé. La comparaison vaut alors NULL, `ifNull` la ramène à « cohérent ».
    ifNull(discharge_ts >= admission_ts, true) AS est_coherent,

    source_file,
    last_ingest_date
FROM
(
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
)
