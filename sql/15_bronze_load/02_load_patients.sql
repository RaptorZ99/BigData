-- Chargement d'un jour de patients depuis le lake.
-- Les colonnes sont lues en String puis typées explicitement : le typage est un
-- acte de la couche bronze, visible et testable, plutôt qu'une inférence opaque.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux — les deux
-- fonctions de table n'ont pas la même signature, mais elles rendent la même chose.
INSERT INTO eds_bronze.patients
SELECT
    patient_pseudo,
    toUInt16OrZero(birth_year)              AS birth_year,
    upperUTF8(trim(sex))                    AS sex,
    trim(region_code)                       AS region_code,
    '{source_file}'                         AS _source_file,
    toDate('{ingest_date}')                 AS _ingest_date,
    now()                                   AS _loaded_at
FROM {lake_source};
