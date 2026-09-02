{{ config(order_by='stay_id') }}
-- Séjours écartés par le contrôle de cohérence temporelle, avec leur motif.
-- On ne supprime jamais en silence : les lignes rejetées restent consultables.
--
-- Le rejet porte sur ce seul fait : les horodatages du séjour sont inexploitables,
-- donc ni sa durée ni sa position dans le calendrier ne peuvent être calculées. Les
-- diagnostics et les relevés rattachés à ces séjours restent, eux, dans l'entrepôt
-- (voir l'encadré de `stg_sejours`).
SELECT
    stay_id,
    patient_pseudo,
    service_code,
    admission_ts,
    discharge_ts,
    admission_mode,
    discharge_mode,
    'discharge_before_admission'                       AS reject_reason,
    'Date de sortie antérieure à la date d''admission' AS reject_label,
    source_file       AS _source_file,
    last_ingest_date  AS _ingest_date,
    now()             AS _rejected_at
FROM {{ ref('stg_sejours') }}
WHERE NOT est_coherent
