-- Un séjour en cours n'a pas de durée : le compter avec sa durée partielle tirerait la
-- DMS vers le bas. Le contrôle vérifie qu'aucun séjour ouvert n'alimente kpi_dms_service,
-- en comparant le total des sorties agrégées au nombre de séjours réellement terminés.
SELECT
    (SELECT sum(nb_sorties) FROM {{ ref('kpi_dms_service') }})               AS agrege,
    (SELECT countIf(discharge_ts IS NOT NULL) FROM {{ ref('fact_sejour') }}) AS attendu
HAVING agrege != attendu
