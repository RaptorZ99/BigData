{{ config(order_by='(releve_date, service_code)') }}
-- Relevés de constantes en alerte, par jour et par service (REA et CARDIO).
--
-- `service_code` étant porté par le fait lui-même, aucune jointure vers fact_sejour
-- n'est nécessaire : une seule étoile suffit à répondre.
SELECT
    m.releve_date                                       AS releve_date,
    m.service_code                                      AS service_code,
    d.service_label                                     AS service_label,
    count()                                             AS nb_releves,
    countIf(m.is_alert)                                 AS nb_alertes,
    countIf(m.alert_hr)                                 AS nb_alertes_frequence_cardiaque,
    countIf(m.alert_spo2)                               AS nb_alertes_saturation,
    countIf(m.alert_temp)                               AS nb_alertes_temperature,
    round(100.0 * countIf(m.is_alert) / count(), 1)     AS pct_alertes,
    uniqExact(m.stay_id)                                AS nb_sejours_monitores
FROM {{ ref('fact_monitoring') }} AS m
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
GROUP BY releve_date, service_code, service_label
