-- Chargement d'un jour de patients depuis le lake.
-- Les colonnes sont lues en String puis typées explicitement : le typage est un
-- acte de la couche bronze, visible et testable, plutôt qu'une inférence opaque.
INSERT INTO eds_bronze.patients
SELECT
    patient_pseudo,
    toUInt16OrZero(birth_year)              AS birth_year,
    upperUTF8(trim(sex))                    AS sex,
    trim(region_code)                       AS region_code,
    '{source_file}'                         AS _source_file,
    toDate('{ingest_date}')                 AS _ingest_date,
    now()                                   AS _loaded_at
FROM file(
    '{source_file}',
    'CSVWithNames',
    'patient_pseudo String, birth_year String, sex String, region_code String'
);
