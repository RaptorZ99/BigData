-- Description des services (catégorie, capacité en lits, pôle).
-- `toUInt16OrNull` et non `OrZero` : une capacité absente ou illisible devient NULL.
-- Un zéro serait une valeur — et une densité d'actes divisée par zéro lits.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux.
INSERT INTO eds_bronze.description_service
SELECT
    upperUTF8(trim(service_code))   AS service_code,
    lowerUTF8(trim(categorie))      AS categorie,
    toUInt16OrNull(capacite_lits)   AS capacite_lits,
    trim(pole)                      AS pole,
    '{source_file}'                 AS _source_file,
    toDate('{ingest_date}')         AS _ingest_date,
    now()                           AS _loaded_at
FROM {lake_source};
