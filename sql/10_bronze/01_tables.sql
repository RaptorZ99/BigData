-- Couche bronze : les fichiers du lake deviennent des tables typées, sans autre
-- transformation que le typage. Aucune règle métier ici — c'est le rôle de silver.
--
-- Deux invariants portés par cette couche :
--   * PARTITION BY _ingest_date  → rejouer un jour = DROP PARTITION + INSERT,
--     donc un chargement idempotent sans état intermédiaire à nettoyer ;
--   * colonnes _source_file / _ingest_date / _loaded_at → lignage complet,
--     chaque ligne sait de quel fichier et de quel run elle provient.

CREATE TABLE IF NOT EXISTS eds_bronze.patients
(
    patient_pseudo String    COMMENT 'Pseudonyme HMAC-SHA256 (aucun IPP en clair)',
    birth_year     UInt16    COMMENT 'Année de naissance (date complète généralisée)',
    sex            LowCardinality(String),
    region_code    LowCardinality(String),

    _source_file   String    COMMENT 'Fichier du lake dont provient la ligne',
    _ingest_date   Date      COMMENT 'Jour de dépôt par le CHU',
    _loaded_at     DateTime  DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (patient_pseudo)
COMMENT 'Patients tels que déposés (fichiers cumulatifs : un patient revient chaque jour)';

CREATE TABLE IF NOT EXISTS eds_bronze.sejours
(
    stay_id        String,
    patient_pseudo String,
    service_code   LowCardinality(String),
    admission_ts   DateTime,
    discharge_ts   Nullable(DateTime) COMMENT 'NULL = séjour en cours (légitime)',
    admission_mode LowCardinality(String),
    discharge_mode LowCardinality(Nullable(String)),

    _source_file   String,
    _ingest_date   Date,
    _loaded_at     DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (stay_id)
COMMENT 'Séjours hospitaliers tels que déposés, typés sans filtrage';

CREATE TABLE IF NOT EXISTS eds_bronze.diagnostics
(
    stay_id      String,
    code_cim10   LowCardinality(String),
    diag_type    LowCardinality(String) COMMENT 'principal | associe',

    _source_file String,
    _ingest_date Date,
    _loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (stay_id, code_cim10)
COMMENT 'Diagnostics CIM-10, JSON imbriqué aplati à une ligne par code';

CREATE TABLE IF NOT EXISTS eds_bronze.monitoring
(
    stay_id      String,
    ts           DateTime,
    heart_rate   Int32   COMMENT 'bpm — valeurs aberrantes conservées ici, écartées en silver',
    spo2         Int32   COMMENT '%',
    temp_c       Float32 COMMENT '°C',

    _source_file String,
    _ingest_date Date,
    _loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (stay_id, ts)
COMMENT 'Constantes au chevet : le flux le plus volumineux (services REA et CARDIO)';

CREATE TABLE IF NOT EXISTS eds_bronze.services
(
    service_code  String,
    service_label String,

    _source_file  String,
    _ingest_date  Date,
    _loaded_at    DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (service_code)
COMMENT 'Référentiel des services hospitaliers';

CREATE TABLE IF NOT EXISTS eds_bronze.cim10
(
    code_cim10   String,
    libelle      String,

    _source_file String,
    _ingest_date Date,
    _loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (code_cim10)
COMMENT 'Référentiel CIM-10 : code diagnostic → libellé';
