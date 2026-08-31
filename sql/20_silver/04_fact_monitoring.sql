-- Étoile 2 — fact_monitoring, grain : un relevé de constantes au chevet.
-- Dimension directe : dim_service (service_code propagé depuis le séjour), ce
-- qui rend l'indicateur « relevés en alerte par jour et par service »
-- calculable sans jointure fait-à-fait.
--
-- Minimisation RGPD : `patient_pseudo` n'est volontairement PAS propagé ici.
-- Aucun besoin métier ne l'exige, donc la donnée ne descend pas jusqu'à cette
-- table — c'est le principe « ne conserver que ce qui est utile à l'usage ».
--
-- Règles qualité :
--   Q4  constante hors plage physiologique → REJET, avec le motif exact
--       (FC 20–250 bpm · SpO2 50–100 % · température 30–45 °C)
--   --  séjour parent écarté ou inconnu   → REJET en cascade
--   Q8  relevé postérieur à la sortie     → FLAG (contrôle actif)

-- ── Relevés écartés, avec leur motif ────────────────────────────────────────
CREATE OR REPLACE TABLE eds_silver.monitoring_rejets
ENGINE = MergeTree
ORDER BY (stay_id, ts)
COMMENT 'Relevés écartés (hors plage physiologique ou séjour parent invalide), motif conservé'
AS
WITH controles AS
(
    SELECT
        m.stay_id                                          AS stay_id,
        m.ts                                               AS ts,
        m.heart_rate                                       AS heart_rate,
        m.spo2                                             AS spo2,
        m.temp_c                                           AS temp_c,
        m._source_file                                     AS _source_file,
        m._ingest_date                                     AS _ingest_date,
        arrayFilter(x -> x != '', [
            if(m.heart_rate < 20  OR m.heart_rate > 250, 'hr_out_of_range',      ''),
            if(m.spo2       < 50  OR m.spo2       > 100, 'spo2_out_of_range',    ''),
            if(m.temp_c     < 30  OR m.temp_c     > 45,  'temp_out_of_range',    ''),
            if(s.stay_id = '',                           'parent_stay_rejected', '')
        ])                                                 AS motifs
    FROM eds_bronze.monitoring AS m
    LEFT JOIN eds_silver.fact_sejour AS s USING (stay_id)
)
SELECT
    stay_id,
    ts,
    heart_rate,
    spo2,
    temp_c,
    arrayStringConcat(motifs, '+') AS reject_reason,
    _source_file,
    _ingest_date,
    now() AS _rejected_at
FROM controles
WHERE length(motifs) > 0;

-- ── Fait monitoring ─────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE eds_silver.fact_monitoring
ENGINE = MergeTree
ORDER BY (service_code, ts)
COMMENT 'Fait monitoring (grain : 1 relevé) — étoile sur dim_service, sans identifiant patient'
AS
SELECT
    m.stay_id                                   AS stay_id,
    s.service_code                              AS service_code,
    m.ts                                        AS ts,
    toDate(m.ts)                                AS releve_date,

    -- Mesures.
    m.heart_rate                                AS heart_rate,
    m.spo2                                      AS spo2,
    m.temp_c                                    AS temp_c,

    -- Seuils d'alerte clinique — hypothèses de travail documentées au rapport
    -- (bradycardie/tachycardie, désaturation, fièvre).
    m.heart_rate < 40 OR m.heart_rate > 130     AS alert_hr,
    m.spo2 < 90                                 AS alert_spo2,
    m.temp_c >= 38.5                            AS alert_temp,
    (m.heart_rate < 40 OR m.heart_rate > 130)
        OR m.spo2 < 90
        OR m.temp_c >= 38.5                     AS is_alert,

    -- Q8 : relevé postérieur à la sortie du patient. Contrôle actif — attendu
    -- à 0 une fois les séjours incohérents écartés en cascade.
    ifNull(m.ts > s.discharge_ts, false)        AS is_after_discharge,

    m._source_file                              AS _source_file,
    m._ingest_date                              AS _ingest_date,
    now()                                       AS _built_at
FROM eds_bronze.monitoring AS m
INNER JOIN eds_silver.fact_sejour AS s USING (stay_id)
WHERE m.heart_rate BETWEEN 20 AND 250
  AND m.spo2       BETWEEN 50 AND 100
  AND m.temp_c     BETWEEN 30 AND 45;
