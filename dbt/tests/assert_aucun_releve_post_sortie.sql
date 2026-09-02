-- Q8 : contrôle actif. Un relevé de constantes postérieur à la sortie du patient est
-- une incohérence de la source. Le flag n'est évalué que sur les séjours
-- temporellement cohérents — sur les autres, c'est la date de sortie elle-même qui est
-- fausse, et la comparaison n'aurait aucun sens.
SELECT stay_id, ts
FROM {{ ref('fact_monitoring') }}
WHERE is_after_discharge
