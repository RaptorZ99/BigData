-- Tables d'exploitation : elles répondent à « d'où vient cette donnée, quand
-- a-t-elle été traitée, et qu'a-t-on écarté ? ». C'est le socle de la
-- traçabilité exigée par le sujet et de l'idempotence du pipeline.

-- Journal d'ingestion : une ligne par (domaine, jour, fichier) traité.
-- Le checksum du fichier source sert de clé d'idempotence : un fichier déjà
-- ingéré à l'identique est sauté, un fichier modifié est rejoué.
-- ReplacingMergeTree : rejouer un jour remplace la ligne au lieu d'empiler.
CREATE TABLE IF NOT EXISTS ops.ingest_log
(
    domain       LowCardinality(String),
    ingest_date  Date,
    source_file  String,
    sha256       String,
    rows_source  Int64   DEFAULT -1,
    rows_loaded  Int64   DEFAULT -1,
    status       Enum8('success' = 1, 'failed' = 2),
    error        String  DEFAULT '',
    run_id       String,
    started_at   DateTime,
    finished_at  DateTime
)
ENGINE = ReplacingMergeTree(finished_at)
ORDER BY (domain, ingest_date, source_file)
COMMENT 'Journal d''ingestion : idempotence par checksum et traçabilité fichier → table';

-- Historique des exécutions du pipeline (une ligne par `eds run`).
--
-- La colonne de version est `updated_at`, et non `started_at` : un run écrit une
-- première ligne à son ouverture puis une seconde à sa clôture, toutes deux avec
-- le même `started_at`. Une version identique laisserait la déduplication choisir
-- arbitrairement, et un run terminé pourrait rester affiché « running ».
CREATE TABLE IF NOT EXISTS ops.pipeline_runs
(
    run_id         String,
    started_at     DateTime,
    finished_at    Nullable(DateTime),
    status         Enum8('running' = 1, 'success' = 2, 'failed' = 3, 'partial' = 4),
    days_processed String   DEFAULT '',
    files_ok       UInt32   DEFAULT 0,
    files_failed   UInt32   DEFAULT 0,
    error          String   DEFAULT '',
    updated_at     DateTime DEFAULT now() COMMENT 'Version : la dernière écriture gagne'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY run_id
COMMENT 'Exécutions du pipeline : quand, quoi, et avec quel résultat';

ALTER TABLE ops.pipeline_runs
    ADD COLUMN IF NOT EXISTS updated_at DateTime DEFAULT now()
    COMMENT 'Version : la dernière écriture gagne';

-- `ops.quality_report` n'est PAS créée ici : c'est un modèle dbt
-- (`dbt/models/ops/quality_report.sql`), matérialisé en incrémental avec son TTL
-- d'un an. Un seul propriétaire par table — deux DDL concurrentes finiraient par
-- diverger, et c'est dbt qui sait dans quel ordre la remplir.
--
-- `ingest_log` et `pipeline_runs` restent ici : elles décrivent l'orchestration,
-- que Python écrit directement, et non la transformation.
