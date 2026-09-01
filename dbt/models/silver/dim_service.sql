{{ config(order_by='service_code') }}
-- Dimension conformée service hospitalier (référentiel du CHU).
SELECT
    service_code,
    service_label,
    source_file      AS _source_file,
    last_ingest_date AS _ingest_date,
    now()            AS _built_at
FROM
(
    SELECT
        service_code,
        argMax(service_label, _ingest_date) AS service_label,
        argMax(_source_file, _ingest_date)  AS source_file,
        max(_ingest_date)                   AS last_ingest_date
    FROM {{ source('bronze', 'services') }}
    GROUP BY service_code
)
