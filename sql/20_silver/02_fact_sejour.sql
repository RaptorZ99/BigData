-- Étoile 1 — fact_sejour, grain : un séjour hospitalier.
-- Dimensions directes : dim_patient (patient_pseudo), dim_service (service_code).
-- `stay_id` est la dimension dégénérée qui relie les trois étoiles.
--
-- Règles qualité appliquées ici :
--   Q2  discharge_ts < admission_ts        → REJET (incohérence temporelle)
--   Q3  discharge_ts vide                  → CONSERVÉ (séjour en cours, légitime)
--   Q5  discharge_mode vide                → CONSERVÉ en NULL
--   Q7  admission après un décès antérieur → FLAG (signalé, non rejeté)

-- ── Séjours écartés, avec leur motif ────────────────────────────────────────
-- On ne supprime jamais en silence : les lignes rejetées restent consultables.
CREATE OR REPLACE TABLE eds_silver.sejours_rejets
ENGINE = MergeTree
ORDER BY stay_id
COMMENT 'Séjours écartés par les contrôles qualité, avec le motif et le lignage'
AS
WITH dedup AS
(
    SELECT
        stay_id,
        argMax(patient_pseudo, _ingest_date) AS patient_pseudo,
        argMax(service_code, _ingest_date)   AS service_code,
        argMax(admission_ts, _ingest_date)   AS admission_ts,
        argMax(discharge_ts, _ingest_date)   AS discharge_ts,
        argMax(admission_mode, _ingest_date) AS admission_mode,
        argMax(discharge_mode, _ingest_date) AS discharge_mode,
        argMax(_source_file, _ingest_date)   AS source_file,
        max(_ingest_date)                    AS last_ingest_date
    FROM eds_bronze.sejours
    GROUP BY stay_id
)
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
FROM dedup
WHERE discharge_ts IS NOT NULL
  AND discharge_ts < admission_ts;

-- ── Fait séjour ─────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE eds_silver.fact_sejour
ENGINE = MergeTree
ORDER BY (stay_id)
COMMENT 'Fait séjour (grain : 1 séjour) — étoile sur dim_patient et dim_service'
AS
WITH dedup AS
(
    SELECT
        stay_id,
        argMax(patient_pseudo, _ingest_date) AS patient_pseudo,
        argMax(service_code, _ingest_date)   AS service_code,
        argMax(admission_ts, _ingest_date)   AS admission_ts,
        argMax(discharge_ts, _ingest_date)   AS discharge_ts,
        argMax(admission_mode, _ingest_date) AS admission_mode,
        argMax(discharge_mode, _ingest_date) AS discharge_mode,
        argMax(_source_file, _ingest_date)   AS source_file,
        max(_ingest_date)                    AS last_ingest_date
    FROM eds_bronze.sejours
    GROUP BY stay_id
),
valides AS
(
    SELECT *
    FROM dedup
    -- Q2 : on écarte les incohérences temporelles.
    -- Q3 : un séjour sans date de sortie est conservé (patient hospitalisé).
    WHERE discharge_ts IS NULL
       OR discharge_ts >= admission_ts
)
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
       dateDiff('hour', admission_ts, discharge_ts))       AS duree_heures,
    if(discharge_ts IS NULL, NULL,
       round(dateDiff('minute', admission_ts, discharge_ts) / 1440.0, 3)) AS duree_jours,

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
FROM valides;
