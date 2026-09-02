{{ config(materialized='ephemeral') }}
-- Déduplication des actes au grain du fait : (séjour, code, horodatage).
--
-- Même règle que pour le monitoring : aujourd'hui aucun triplet n'apparaît deux fois,
-- mais un redépôt corrigé du CHU arriverait sous un autre `_ingest_date` et doublerait
-- les actes et la facturation sans ce `argMax`. L'idempotence ne se fait pas dépendre
-- de la propreté du dépôt.
SELECT
    stay_id,
    code_ccam,
    acte_ts,
    argMax(_source_file, _ingest_date) AS source_file,
    max(_ingest_date)                  AS last_ingest_date
FROM {{ source('bronze', 'actes') }}
GROUP BY stay_id, code_ccam, acte_ts
