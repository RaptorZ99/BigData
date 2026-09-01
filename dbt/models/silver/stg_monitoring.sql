{{ config(materialized='ephemeral') }}
-- Déduplication du monitoring au grain du fait : (séjour, horodatage).
--
-- Les fichiers quotidiens couvrent J → J+2 et se recouvrent donc dans le temps.
-- Aujourd'hui aucun couple n'apparaît deux fois, mais un redépôt corrigé du CHU
-- arriverait sous un autre `_ingest_date` et doublerait relevés et alertes sans ce
-- `argMax`. L'idempotence ne se fait pas dépendre de la propreté du dépôt.
SELECT
    stay_id,
    ts,
    argMax(heart_rate, _ingest_date)   AS heart_rate,
    argMax(spo2, _ingest_date)         AS spo2,
    argMax(temp_c, _ingest_date)       AS temp_c,
    argMax(_source_file, _ingest_date) AS source_file,
    max(_ingest_date)                  AS last_ingest_date
FROM {{ source('bronze', 'monitoring') }}
GROUP BY stay_id, ts
