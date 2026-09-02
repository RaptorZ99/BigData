{{ config(order_by='(stay_id, acte_ts)') }}
-- Actes écartés : leur séjour n'existe pas dans le dépôt, donc ni service ni période
-- ne sont résolubles. On ne supprime jamais en silence : les lignes restent consultables.
SELECT
    a.stay_id                                   AS stay_id,
    a.code_ccam                                 AS code_ccam,
    a.acte_ts                                   AS acte_ts,
    'sejour_inconnu'                            AS reject_reason,
    'Séjour absent du dépôt du CHU'             AS reject_label,
    a.source_file                               AS _source_file,
    a.last_ingest_date                          AS _ingest_date,
    now()                                       AS _rejected_at
FROM {{ ref('stg_actes') }} AS a
LEFT JOIN {{ ref('stg_sejours') }} AS s USING (stay_id)
WHERE s.stay_id = ''
