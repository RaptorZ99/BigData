-- Chargement d'un jour de monitoring (Parquet, le flux le plus volumineux).
-- Le schéma est lu nativement par ClickHouse ; les valeurs aberrantes sont
-- conservées telles quelles à ce stade — elles seront écartées et tracées en
-- silver, jamais supprimées en silence.
-- Le lecteur du lake est injecté par `load_bronze.py` : `file(...)` en cible locale,
-- `azureBlobStorage(...)` en cible Azure. Un seul script pour les deux — les deux
-- fonctions de table n'ont pas la même signature, mais elles rendent la même chose.
INSERT INTO eds_bronze.monitoring
SELECT
    stay_id,
    ts,
    toInt32(heart_rate)     AS heart_rate,
    toInt32(spo2)           AS spo2,
    toFloat32(temp_c)       AS temp_c,
    '{source_file}'         AS _source_file,
    toDate('{ingest_date}') AS _ingest_date,
    now()                   AS _loaded_at
FROM {lake_source};
