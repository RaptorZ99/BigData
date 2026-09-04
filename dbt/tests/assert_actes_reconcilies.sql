-- Les tables d'actes se réconcilient exactement avec la table de faits.
--
-- Les KPI 2, 4 et 5 publient trois lectures d'une même agrégation (`int_actes_service`),
-- le KPI 3 une répartition par code. Chacune doit totaliser le nombre de lignes de
-- `fact_acte` : une jointure fait-à-fait multiplierait chaque séjour par ses actes, et
-- ces sommes exploseraient — c'est le garde-fou de la réponse au piège n° 2. Même
-- contrôle sur le montant facturé.
SELECT
    (SELECT count() FROM {{ ref('fact_acte') }})                                  AS faits,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_actes_service') }})                   AS par_service,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_actes_type') }})                      AS par_type,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_densite_lits') }})                    AS par_lit,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_facturation_service') }})             AS par_facturation,
    (SELECT ifNull(sum(montant_euros), 0) FROM {{ ref('fact_acte') }})           AS montant_faits,
    (SELECT sum(montant_facture_euros) FROM {{ ref('kpi_facturation_service') }}) AS montant_service
HAVING faits != par_service
    OR faits != par_type
    OR faits != par_lit
    OR faits != par_facturation
    OR montant_faits != montant_service
