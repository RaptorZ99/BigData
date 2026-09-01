{{ config(order_by='code_cim10') }}
-- Dimension CIM-10 : code diagnostic → libellé (nomenclature OMS).
SELECT
    code_cim10,
    libelle,
    source_file      AS _source_file,
    last_ingest_date AS _ingest_date,
    now()            AS _built_at
FROM
(
    SELECT
        code_cim10,
        argMax(libelle, _ingest_date)      AS libelle,
        argMax(_source_file, _ingest_date) AS source_file,
        max(_ingest_date)                  AS last_ingest_date
    FROM {{ source('bronze', 'cim10') }}
    GROUP BY code_cim10
)
