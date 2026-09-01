-- Q8 : contrôle actif. Les relevés postérieurs à la sortie appartenaient tous aux
-- séjours temporellement incohérents ; ils partent en cascade. Le flag doit donc
-- valoir 0 après nettoyage — si ce test se met à échouer, c'est que la cascade a été
-- rompue, pas que les données ont changé.
SELECT stay_id, ts
FROM {{ ref('fact_monitoring') }}
WHERE is_after_discharge
