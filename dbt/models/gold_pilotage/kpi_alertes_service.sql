{{ config(order_by='service_code') }}
-- Ventilation par service de la surveillance des constantes (cf. KPI 4).
--
-- `service_code` étant porté par le fait lui-même, aucune jointure vers fact_sejour
-- n'est nécessaire : une seule étoile suffit à répondre.
--
-- Le monitoring ne couvre que les services équipés de capteurs au chevet — en
-- pratique réanimation et cardiologie. Ne pas lire l'absence des autres services
-- comme une absence d'alertes.
SELECT
    m.service_code                                      AS service_code,
    d.service_label                                     AS service_label,
    count()                                             AS nb_releves,
    countIf(m.is_alert)                                 AS nb_alertes,
    round(100.0 * countIf(m.is_alert) / count(), 1)     AS taux_alertes_pct,
    countIf(m.alert_hr)                                 AS nb_alertes_frequence_cardiaque,
    countIf(m.alert_spo2)                               AS nb_alertes_saturation,
    countIf(m.alert_temp)                               AS nb_alertes_temperature,
    uniqExact(m.stay_id)                                AS nb_sejours_monitores
FROM {{ ref('fact_monitoring') }} AS m
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
GROUP BY service_code, service_label
