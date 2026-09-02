-- Référentiel CCAM (Classification Commune des Actes Médicaux) : code → libellé, tarif.
-- Le tarif suit la même règle que la capacité : absent ou illisible → NULL, jamais 0.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux.
INSERT INTO eds_bronze.ccam
SELECT
    upperUTF8(trim(code_ccam))  AS code_ccam,
    trim(libelle)               AS libelle,
    toUInt32OrNull(tarif_euros) AS tarif_euros,
    '{source_file}'             AS _source_file,
    toDate('{ingest_date}')     AS _ingest_date,
    now()                       AS _loaded_at
FROM {lake_source};
