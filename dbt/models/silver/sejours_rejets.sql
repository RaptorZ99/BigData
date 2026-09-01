{{ config(order_by='stay_id') }}
-- Séjours écartés par le contrôle de cohérence temporelle, avec leur motif.
-- On ne supprime jamais en silence : les lignes rejetées restent consultables.
SELECT
    stay_id,
    patient_pseudo,
    service_code,
    admission_ts,
    discharge_ts,
    admission_mode,
    discharge_mode,
    'discharge_before_admission' AS reject_reason,
    'Date de sortie antérieure à la date d''admission' AS reject_label,
    source_file       AS _source_file,
    last_ingest_date  AS _ingest_date,
    now()             AS _rejected_at
FROM {{ ref('stg_sejours') }}
WHERE discharge_ts IS NOT NULL
  AND discharge_ts < admission_ts
