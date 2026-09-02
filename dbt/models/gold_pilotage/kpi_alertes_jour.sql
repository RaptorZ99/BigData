{{ config(order_by='jour') }}
-- KPI 4 — Surveillance des constantes : relevés en alerte par jour.
--
-- Grain : le jour du relevé, tous services confondus. C'est la courbe de vigilance
-- que lit le cadre de garde ; la ventilation par service vit dans
-- `kpi_alertes_service`.
--
-- Seuils de vigilance (portés par `fact_monitoring`) : FC < 50 ou > 100 bpm,
-- SpO2 < 92 %, température > 38,5 °C.
SELECT
    releve_date                                     AS jour,
    count()                                         AS nb_releves,
    countIf(is_alert)                               AS nb_alertes,
    round(100.0 * countIf(is_alert) / count(), 1)   AS taux_alertes_pct,
    countIf(alert_hr)                               AS nb_alertes_frequence_cardiaque,
    countIf(alert_spo2)                             AS nb_alertes_saturation,
    countIf(alert_temp)                             AS nb_alertes_temperature
FROM {{ ref('fact_monitoring') }}
GROUP BY jour
