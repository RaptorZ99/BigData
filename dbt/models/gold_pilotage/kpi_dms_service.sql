{{ config(order_by='service_code') }}
-- KPI 1 — Durée Moyenne de Séjour par service.
--
-- Grain : le service. C'est celui de la question métier (« quels services immobilisent
-- le plus longtemps un lit ? ») ; une DMS par jour de sortie répondrait à une autre
-- question et se lirait comme du bruit.
--
-- Seuls les séjours terminés entrent dans la moyenne : compter un séjour en cours
-- avec sa durée partielle tirerait la DMS vers le bas.
--
-- `quantileExact` plutôt que `median` : ce dernier échantillonne au-delà de 8 192
-- lignes par groupe et cesse alors d'être reproductible d'une exécution à l'autre.
SELECT
    f.service_code                              AS service_code,
    d.service_label                             AS service_label,
    count()                                     AS nb_sejours,
    round(avg(f.duree_jours), 2)                AS dms_jours,
    round(avg(f.duree_heures), 1)               AS dms_heures,
    round(quantileExact(0.5)(f.duree_jours), 2) AS duree_mediane_jours,
    round(min(f.duree_jours), 2)                AS duree_min_jours,
    round(max(f.duree_jours), 2)                AS duree_max_jours
FROM {{ ref('fact_sejour') }} AS f
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
WHERE f.discharge_ts IS NOT NULL
GROUP BY service_code, service_label
