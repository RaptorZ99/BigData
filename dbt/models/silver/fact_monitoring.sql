{{ config(order_by='(service_code, ts)') }}
-- Étoile 2 — fact_monitoring, grain : un relevé de constantes au chevet.
-- Dimension directe : dim_service (service_code propagé depuis le séjour), ce qui rend
-- « relevés en alerte par jour et par service » calculable sans jointure fait-à-fait.
--
-- Minimisation RGPD : `patient_pseudo` n'est volontairement PAS propagé ici. Aucun
-- besoin métier ne l'exige, donc la donnée ne descend pas jusqu'à cette table.
--
-- Le service est résolu depuis `stg_sejours`, qui porte TOUS les séjours déposés : un
-- relevé de constantes a son propre horodatage et reste valide même si le séjour
-- parent a une date de sortie aberrante (voir l'encadré de `stg_sejours`).
--
-- Règles qualité :
--   Q4  constante hors plage physiologique → REJET (voir monitoring_rejets)
--   C1  séjour parent absent du dépôt      → REJET (contrôle actif, attendu à 0)
--   Q8  relevé postérieur à la sortie      → FLAG (contrôle actif, attendu à 0)
SELECT
    m.stay_id                                   AS stay_id,
    s.service_code                              AS service_code,
    m.ts                                        AS ts,
    toDate(m.ts)                                AS releve_date,

    -- Mesures.
    m.heart_rate                                AS heart_rate,
    m.spo2                                      AS spo2,
    m.temp_c                                    AS temp_c,

    -- Seuils d'alerte clinique — bradycardie, tachycardie, désaturation, fièvre.
    -- Ce sont des seuils de VIGILANCE, volontairement plus serrés que les bornes de
    -- plausibilité qui filtrent les capteurs en panne : une constante peut être
    -- parfaitement mesurée et cliniquement anormale.
    m.heart_rate < 50 OR m.heart_rate > 100     AS alert_hr,
    m.spo2 < 92                                 AS alert_spo2,
    m.temp_c > 38.5                             AS alert_temp,
    (m.heart_rate < 50 OR m.heart_rate > 100)
        OR m.spo2 < 92
        OR m.temp_c > 38.5                      AS is_alert,

    -- Q8 : relevé postérieur à la sortie du patient. Le contrôle ne se prononce que
    -- sur les séjours temporellement cohérents — sur les autres, la date de sortie
    -- est justement ce qui est faux, et le comparer n'aurait aucun sens.
    ifNull(s.est_coherent AND m.ts > s.discharge_ts, false) AS is_after_discharge,

    m.source_file                               AS _source_file,
    m.last_ingest_date                          AS _ingest_date,
    now()                                       AS _built_at
FROM {{ ref('stg_monitoring') }} AS m
INNER JOIN {{ ref('stg_sejours') }} AS s USING (stay_id)
-- Q4 : bornes de plausibilité physiologique. Hors de ces bornes, c'est le capteur
-- qu'on mesure, pas le patient.
WHERE m.heart_rate BETWEEN 20 AND 250
  AND m.spo2       BETWEEN 50 AND 100
  AND m.temp_c     BETWEEN 30 AND 45
