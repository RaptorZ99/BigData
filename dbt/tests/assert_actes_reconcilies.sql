-- Les vues d'actes se réconcilient exactement avec la table de faits.
--
-- C'est le garde-fou du drill-across : `kpi_actes_service` combine deux faits agrégés
-- séparément puis rejoints sur la dimension. Une jointure fait-à-fait multiplierait
-- chaque séjour par ses actes, et cette somme exploserait. Même contrôle sur la
-- répartition par type, dont les parts doivent couvrir 100 % des actes.
SELECT
    (SELECT count() FROM {{ ref('fact_acte') }})                              AS faits,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_actes_service') }})               AS par_service,
    (SELECT sum(nb_actes) FROM {{ ref('kpi_actes_type') }})                  AS par_type,
    (SELECT ifNull(sum(montant_euros), 0) FROM {{ ref('fact_acte') }})       AS montant_faits,
    (SELECT sum(montant_facture_euros) FROM {{ ref('kpi_actes_service') }})  AS montant_service,
    (SELECT round(sum(part_pct)) FROM {{ ref('kpi_actes_type') }})           AS somme_des_parts
HAVING faits != par_service
    OR faits != par_type
    OR montant_faits != montant_service
    OR somme_des_parts != 100
