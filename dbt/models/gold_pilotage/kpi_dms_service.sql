{{ config(order_by='(service_code, discharge_date)') }}
-- Durée Moyenne de Séjour par service et jour de sortie.
--
-- Seuls les séjours terminés entrent dans la moyenne : compter un séjour en cours
-- avec sa durée partielle tirerait la DMS vers le bas.
SELECT
    f.service_code                       AS service_code,
    d.service_label                      AS service_label,
    -- Le filtre WHERE garantit une date de sortie : on lève le caractère nullable
    -- pour pouvoir l'utiliser comme clé de tri.
    assumeNotNull(f.discharge_date)      AS discharge_date,
    count()                              AS nb_sorties,
    round(avg(f.duree_jours), 2)         AS dms_jours,
    round(median(f.duree_jours), 2)      AS duree_mediane_jours,
    round(min(f.duree_jours), 2)         AS duree_min_jours,
    round(max(f.duree_jours), 2)         AS duree_max_jours
FROM {{ ref('fact_sejour') }} AS f
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
WHERE f.discharge_ts IS NOT NULL
GROUP BY service_code, service_label, discharge_date
