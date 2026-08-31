-- Dimensions conformées de la constellation silver.
-- Elles sont partagées par les trois étoiles : un même `dim_patient` sert au
-- pilotage et à la recherche, ce qui garantit que les deux usages comptent les
-- mêmes patients.

-- ── dim_patient ─────────────────────────────────────────────────────────────
-- Règle qualité Q1 : le CHU redépose chaque jour l'intégralité de ses patients
-- (4 800 → 5 400 → 6 000 lignes). On conserve la version la plus récente de
-- chaque patient : `argMax(colonne, _ingest_date)`.
CREATE OR REPLACE TABLE eds_silver.dim_patient
ENGINE = MergeTree
ORDER BY patient_pseudo
COMMENT 'Dimension conformée patient — pseudonymisée, une ligne par patient (dernière version connue)'
AS
SELECT
    patient_pseudo,
    argMax(birth_year, _ingest_date)   AS birth_year,
    argMax(sex, _ingest_date)          AS sex,
    argMax(region_code, _ingest_date)  AS region_code,
    max(_ingest_date)                  AS last_seen_ingest_date,
    min(_ingest_date)                  AS first_seen_ingest_date
FROM eds_bronze.patients
GROUP BY patient_pseudo;

-- ── dim_service ─────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE eds_silver.dim_service
ENGINE = MergeTree
ORDER BY service_code
COMMENT 'Dimension conformée service hospitalier (référentiel du CHU)'
AS
SELECT
    service_code,
    argMax(service_label, _ingest_date) AS service_label
FROM eds_bronze.services
GROUP BY service_code;

-- ── dim_cim10 ───────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE eds_silver.dim_cim10
ENGINE = MergeTree
ORDER BY code_cim10
COMMENT 'Dimension CIM-10 : code diagnostic → libellé (nomenclature OMS)'
AS
SELECT
    code_cim10,
    argMax(libelle, _ingest_date) AS libelle
FROM eds_bronze.cim10
GROUP BY code_cim10;
