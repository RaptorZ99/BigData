-- Référentiel des services (déposé le premier jour).
INSERT INTO eds_bronze.services
SELECT
    upperUTF8(trim(service_code)) AS service_code,
    trim(service_label)           AS service_label,
    '{source_file}'               AS _source_file,
    toDate('{ingest_date}')       AS _ingest_date,
    now()                         AS _loaded_at
FROM file(
    '{source_file}',
    'CSVWithNames',
    'service_code String, service_label String'
);
