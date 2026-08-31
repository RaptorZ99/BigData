-- Chargement d'un jour de séjours depuis le lake.
-- `discharge_ts` vide est légitime (patient encore hospitalisé) : on le convertit
-- en NULL plutôt que d'échouer. Idem pour `discharge_mode`, souvent absent.
INSERT INTO eds_bronze.sejours
SELECT
    trim(stay_id)                                    AS stay_id,
    trim(patient_pseudo)                             AS patient_pseudo,
    upperUTF8(trim(service_code))                    AS service_code,
    parseDateTimeBestEffort(admission_ts)            AS admission_ts,
    parseDateTimeBestEffortOrNull(discharge_ts)      AS discharge_ts,
    lowerUTF8(trim(admission_mode))                  AS admission_mode,
    nullIf(lowerUTF8(trim(discharge_mode)), '')      AS discharge_mode,
    '{source_file}'                                  AS _source_file,
    toDate('{ingest_date}')                          AS _ingest_date,
    now()                                            AS _loaded_at
FROM file(
    '{source_file}',
    'CSVWithNames',
    'stay_id String, patient_pseudo String, service_code String, admission_ts String,
     discharge_ts String, admission_mode String, discharge_mode String'
);
