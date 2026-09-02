-- Évolution du 29 août 2026 : le CHU décrit ses services plus finement et dépose un
-- nouveau flux d'actes médicaux. Trois tables s'ajoutent ; les six premières ne bougent
-- pas — c'est ce qui fait de cette évolution un incrément, pas une refonte.
--
-- Mêmes invariants que les tables historiques : partition par jour de dépôt (rejeu
-- idempotent) et lignage complet sur chaque ligne.

CREATE TABLE IF NOT EXISTS eds_bronze.actes
(
    stay_id      String,
    code_ccam    LowCardinality(String) COMMENT 'Code de l''acte (nomenclature CCAM)',
    acte_ts      DateTime               COMMENT 'Date et heure de réalisation',

    _source_file String,
    _ingest_date Date,
    _loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (stay_id, acte_ts)
COMMENT 'Actes médicaux réalisés pendant les séjours — flux déposé à partir du 29 août 2026';

CREATE TABLE IF NOT EXISTS eds_bronze.description_service
(
    service_code  String,
    categorie     LowCardinality(String) COMMENT 'Type de service : regroupe plusieurs services',
    capacite_lits Nullable(UInt16)       COMMENT 'Nombre de lits — NULL si absent ou invalide, jamais 0 par défaut',
    pole          LowCardinality(String) COMMENT 'Pôle hospitalier',

    _source_file  String,
    _ingest_date  Date,
    _loaded_at    DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (service_code)
COMMENT 'Description des services : catégorie, capacité, pôle — complète le référentiel des services';

CREATE TABLE IF NOT EXISTS eds_bronze.ccam
(
    code_ccam    String,
    libelle      String,
    tarif_euros  Nullable(UInt32) COMMENT 'Tarif T2A en euros — NULL si absent ou invalide',

    _source_file String,
    _ingest_date Date,
    _loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY _ingest_date
ORDER BY (code_ccam)
COMMENT 'Référentiel CCAM : code d''acte → libellé et tarif';
