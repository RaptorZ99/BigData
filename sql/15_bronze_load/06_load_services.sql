-- Référentiel des services (déposé le premier jour).
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux — les deux
-- fonctions de table n'ont pas la même signature, mais elles rendent la même chose.
INSERT INTO eds_bronze.services
SELECT
    upperUTF8(trim(service_code)) AS service_code,
    trim(service_label)           AS service_label,
    '{source_file}'               AS _source_file,
    toDate('{ingest_date}')       AS _ingest_date,
    now()                         AS _loaded_at
FROM {lake_source};
