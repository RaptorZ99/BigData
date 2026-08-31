-- Référentiel CIM-10 (Classification Internationale des Maladies, 10e révision).
INSERT INTO eds_bronze.cim10
SELECT
    upperUTF8(trim(code_cim10)) AS code_cim10,
    trim(libelle)               AS libelle,
    '{source_file}'             AS _source_file,
    toDate('{ingest_date}')     AS _ingest_date,
    now()                       AS _loaded_at
FROM file(
    '{source_file}',
    'CSVWithNames',
    'code_cim10 String, libelle String'
);
