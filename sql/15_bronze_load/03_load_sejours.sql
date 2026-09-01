-- Chargement d'un jour de séjours depuis le lake.
-- `discharge_ts` vide est légitime (patient encore hospitalisé) : on le convertit
-- en NULL plutôt que d'échouer. Idem pour `discharge_mode`, souvent absent.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux — les deux
-- fonctions de table n'ont pas la même signature, mais elles rendent la même chose.
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
FROM {lake_source};
