{{ config(order_by='(stay_id, ts)') }}
-- Relevés écartés, avec leur motif exact — hors plage physiologique
-- (FC 20-250 bpm · SpO2 50-100 % · température 30-45 °C) ou séjour parent invalide.
--
-- Un relevé peut cumuler plusieurs motifs : ils sont concaténés plutôt que réduits
-- au premier, sans quoi le rapport qualité compterait mal.
WITH controles AS
(
    SELECT
        m.stay_id                                          AS stay_id,
        m.ts                                               AS ts,
        m.heart_rate                                       AS heart_rate,
        m.spo2                                             AS spo2,
        m.temp_c                                           AS temp_c,
        m.source_file                                      AS _source_file,
        m.last_ingest_date                                 AS _ingest_date,
        arrayFilter(x -> x != '', [
            if(m.heart_rate < 20  OR m.heart_rate > 250, 'hr_out_of_range',      ''),
            if(m.spo2       < 50  OR m.spo2       > 100, 'spo2_out_of_range',    ''),
            if(m.temp_c     < 30  OR m.temp_c     > 45,  'temp_out_of_range',    ''),
            if(s.stay_id = '',                           'parent_stay_rejected', '')
        ])                                                 AS motifs
    FROM {{ ref('stg_monitoring') }} AS m
    LEFT JOIN {{ ref('fact_sejour') }} AS s USING (stay_id)
)
SELECT
    stay_id,
    ts,
    heart_rate,
    spo2,
    temp_c,
    arrayStringConcat(motifs, '+') AS reject_reason,
    _source_file,
    _ingest_date,
    now() AS _rejected_at
FROM controles
WHERE length(motifs) > 0
