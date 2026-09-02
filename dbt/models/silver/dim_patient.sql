{{ config(order_by='patient_pseudo') }}
-- Dimension conformée patient — pseudonymisée, une ligne par patient.
--
-- Règle qualité Q1 : le CHU redépose chaque jour l'intégralité de ses patients
-- (6 000 lignes par dépôt, dont une centaine changent de département d'un jour à
-- l'autre). On conserve la version la plus récente de chacun.
SELECT
    patient_pseudo,
    birth_year,
    sex,
    region_code,
    first_seen_ingest_date,
    source_file      AS _source_file,
    last_ingest_date AS _ingest_date,
    now()            AS _built_at
FROM
(
    SELECT
        patient_pseudo,
        argMax(birth_year, _ingest_date)   AS birth_year,
        argMax(sex, _ingest_date)          AS sex,
        argMax(region_code, _ingest_date)  AS region_code,
        argMax(_source_file, _ingest_date) AS source_file,
        min(_ingest_date)                  AS first_seen_ingest_date,
        max(_ingest_date)                  AS last_ingest_date
    FROM {{ source('bronze', 'patients') }}
    GROUP BY patient_pseudo
)
