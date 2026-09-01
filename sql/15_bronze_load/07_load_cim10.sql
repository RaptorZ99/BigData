-- Référentiel CIM-10 (Classification Internationale des Maladies, 10e révision).
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux — les deux
-- fonctions de table n'ont pas la même signature, mais elles rendent la même chose.
INSERT INTO eds_bronze.cim10
SELECT
    upperUTF8(trim(code_cim10)) AS code_cim10,
    trim(libelle)               AS libelle,
    '{source_file}'             AS _source_file,
    toDate('{ingest_date}')     AS _ingest_date,
    now()                       AS _loaded_at
FROM {lake_source};
