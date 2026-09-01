{{ config(order_by='(service_code, ts)') }}
-- Étoile 2 — fact_monitoring, grain : un relevé de constantes au chevet.
-- Dimension directe : dim_service (service_code propagé depuis le séjour), ce qui rend
-- « relevés en alerte par jour et par service » calculable sans jointure fait-à-fait.
--
-- Minimisation RGPD : `patient_pseudo` n'est volontairement PAS propagé ici. Aucun
-- besoin métier ne l'exige, donc la donnée ne descend pas jusqu'à cette table.
--
-- Règles qualité :
--   Q4  constante hors plage physiologique → REJET (voir monitoring_rejets)
--   --  séjour parent écarté ou inconnu   → REJET en cascade
--   Q8  relevé postérieur à la sortie     → FLAG (contrôle actif, attendu à 0)
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

    m.source_file                               AS _source_file,
    m.last_ingest_date                          AS _ingest_date,
    now()                                       AS _built_at
FROM {{ ref('stg_monitoring') }} AS m
INNER JOIN {{ ref('fact_sejour') }} AS s USING (stay_id)
WHERE m.heart_rate BETWEEN 20 AND 250
  AND m.spo2       BETWEEN 50 AND 100
  AND m.temp_c     BETWEEN 30 AND 45
