{{ config(order_by='code_ccam') }}
-- Dimension CCAM : code d'acte médical → libellé et tarif T2A (Classification Commune
-- des Actes Médicaux). Déposée le 29 août 2026 avec le flux d'actes.
SELECT
    code_ccam,
    libelle,
    tarif_euros,
    source_file      AS _source_file,
    last_ingest_date AS _ingest_date,
    now()            AS _built_at
FROM
(
    SELECT
        code_ccam,
        argMax(libelle, _ingest_date)      AS libelle,
        argMax(tarif_euros, _ingest_date)  AS tarif_euros,
        argMax(_source_file, _ingest_date) AS source_file,
        max(_ingest_date)                  AS last_ingest_date
    FROM {{ source('bronze', 'ccam') }}
    GROUP BY code_ccam
)
