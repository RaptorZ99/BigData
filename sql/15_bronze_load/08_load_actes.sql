-- Chargement d'un jour d'actes médicaux (Parquet, comme le monitoring).
-- Le schéma est lu nativement par ClickHouse ; les colonnes arrivent Nullable et sont
-- ramenées à leur type bronze. Un acte sans séjour ou sans code ne peut pas être
-- rattaché à quoi que ce soit : il est conservé ici tel quel, et c'est silver qui
-- l'écartera avec son motif — jamais une suppression en silence au chargement.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux.
INSERT INTO eds_bronze.actes
SELECT
    trim(ifNull(stay_id, ''))               AS stay_id,
    upperUTF8(trim(ifNull(code_ccam, '')))  AS code_ccam,
    toDateTime(acte_ts)                     AS acte_ts,
    '{source_file}'                         AS _source_file,
    toDate('{ingest_date}')                 AS _ingest_date,
    now()                                   AS _loaded_at
FROM {lake_source};
