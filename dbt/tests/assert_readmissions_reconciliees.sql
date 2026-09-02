-- Le taux global et sa ventilation par service viennent de la même définition
-- (`readmission_sejour`) : leurs totaux doivent coïncider exactement.
--
-- Deux tables qui affichent deux chiffres différents pour le même indicateur, c'est
-- la façon la plus sûre de perdre la confiance d'une direction.
SELECT
    (SELECT sum(nb_sejours) FROM {{ ref('kpi_readmissions_service') }})         AS sejours_ventiles,
    (SELECT nb_sejours FROM {{ ref('kpi_readmissions_30j') }})                  AS sejours_global,
    (SELECT sum(nb_readmissions_30j) FROM {{ ref('kpi_readmissions_service') }}) AS readm_ventilees,
    (SELECT nb_readmissions_30j FROM {{ ref('kpi_readmissions_30j') }})          AS readm_global
HAVING sejours_ventiles != sejours_global OR readm_ventilees != readm_global
