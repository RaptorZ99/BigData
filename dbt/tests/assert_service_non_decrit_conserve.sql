-- Un service absent du référentiel de description ne doit jamais disparaître.
--
-- La jointure vers la description est externe précisément pour cela : le jour où
-- quelqu'un la rendrait interne, NEURO et ses 1 208 séjours sortiraient de tous les
-- indicateurs sans qu'aucun chiffre ne paraisse faux. Ce test compare la dimension au
-- référentiel des services, qui seul décide de son périmètre.
SELECT
    (SELECT count() FROM {{ ref('dim_service') }})                                   AS dimension,
    (SELECT uniqExact(service_code) FROM {{ source('bronze', 'services') }})         AS referentiel
HAVING dimension != referentiel
