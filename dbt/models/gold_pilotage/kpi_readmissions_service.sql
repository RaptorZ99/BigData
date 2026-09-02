{{ config(order_by='service_code') }}
-- Ventilation par service du taux de réadmission à 30 jours (cf. KPI 2).
--
-- Le service porté est celui du séjour **initial** : c'est lui qu'on interroge sur la
-- qualité de la prise en charge, pas celui qui réadmet.
SELECT
    r.service_code                                        AS service_code,
    d.service_label                                       AS service_label,
    count()                                               AS nb_sejours,
    countIf(r.est_readmis)                                AS nb_readmissions_30j,
    round(100.0 * countIf(r.est_readmis) / count(), 2)    AS taux_readmission_30j_pct
FROM {{ ref('readmission_sejour') }} AS r
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
GROUP BY service_code, service_label
