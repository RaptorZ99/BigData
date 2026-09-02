{{ config(order_by='stay_id') }}
-- Étoile 1 — fact_sejour, grain : un séjour hospitalier.
-- Dimensions directes : dim_patient (patient_pseudo), dim_service (service_code).
-- `stay_id` est la dimension dégénérée qui relie les trois étoiles.
--
-- Règles qualité appliquées ici :
--   Q2  discharge_ts < admission_ts        → REJET (voir sejours_rejets)
--   Q3  discharge_ts vide                  → CONSERVÉ (séjour en cours, légitime)
--   Q5  discharge_mode vide                → CONSERVÉ en NULL
--   Q7  admission après un décès antérieur → FLAG (signalé, non rejeté)
SELECT
    stay_id,
    patient_pseudo,
    service_code,
    admission_ts,
    discharge_ts,
    admission_mode,
    discharge_mode,

    -- Axes temporels dérivés (pas de dim_date physique : ClickHouse suffit).
    toDate(admission_ts)                                   AS admission_date,
    toDate(discharge_ts)                                   AS discharge_date,

    -- Mesures. NULL tant que le séjour est en cours : une durée partielle
    -- fausserait la DMS, il vaut mieux ne pas la compter du tout.
    if(discharge_ts IS NULL, NULL,
       dateDiff('minute', admission_ts, discharge_ts) / 60.0)   AS duree_heures,
    if(discharge_ts IS NULL, NULL,
       dateDiff('minute', admission_ts, discharge_ts) / 1440.0) AS duree_jours,

    -- Flags métier.
    discharge_ts IS NULL                                   AS is_ongoing,
    discharge_mode = 'deces'                               AS is_deces,
    admission_mode = 'urgence'                             AS is_admission_urgence,
    service_code = 'URGENCES'                              AS is_service_urgences,

    -- Q7 : admission postérieure à un décès déjà enregistré pour ce patient.
    -- Incohérence de la source : signalée au rapport qualité, pas rejetée
    -- (le séjour lui-même reste temporellement cohérent).
    ifNull(
        admission_ts > minIf(discharge_ts, discharge_mode = 'deces')
            OVER (PARTITION BY patient_pseudo),
        false
    )                                                      AS is_post_mortem_anomaly,

    source_file                                            AS _source_file,
    last_ingest_date                                       AS _ingest_date,
    now()                                                  AS _built_at
FROM {{ ref('stg_sejours') }}
WHERE est_coherent
