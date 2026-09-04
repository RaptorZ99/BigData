{{ config(materialized='ephemeral') }}
-- Actes agrégés au grain du service — calculés UNE fois, publiés trois fois.
--
-- Les KPI 2, 4 et 5 de l'évolution (actes par service, densité par lit, montant
-- facturé) partagent ce grain. Chacun est une table gold à part entière, parce que
-- c'est ainsi que la consigne les pose et qu'un lecteur les cherche ; mais leur
-- agrégation n'est écrite qu'ici, en modèle éphémère que dbt inline dans les trois
-- tables. Trois copies du même GROUP BY finiraient par diverger.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  « Actes par service » sans relier deux tables de faits
--
--  Le service d'un acte est porté par son séjour. Il a été résolu au build et rangé
--  sur `fact_acte` (voir ce modèle) : compter les actes par service est un simple
--  GROUP BY sur le fait, et aucune ligne de fact_acte ne rencontre jamais une ligne
--  de fact_sejour. Le dénominateur d'« actes par séjour » vient du fait lui-même
--  (séjours distincts ayant un acte). La dimension conformée `dim_service` apporte
--  ensuite le libellé et la capacité en lits : le fait agrégé seul, puis joint sur
--  sa dimension — le schéma en étoile lu comme il est conçu.
--
--  Le test `assert_actes_reconcilies` est le garde-fou : la somme des actes de
--  chaque table publiée doit valoir exactement le nombre de lignes de fact_acte.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Ce que comptent les mesures :
--   * `nb_actes` : tous les actes rattachables, y compris les 82 réalisés pendant les
--     68 séjours aux horodatages incohérents — un acte est un fait clinique, le séjour
--     écarté ne l'annule pas (même règle que les diagnostics et les relevés) ;
--   * `nb_sejours_avec_acte` : séjours distincts ayant au moins un acte — le
--     dénominateur d'« actes par séjour » ;
--   * `montant_facture_euros` : somme des tarifs T2A portés par le fait ; un code CCAM
--     inconnu n'a pas de tarif et ne compte pas pour zéro.
--
-- Jointure externe depuis la dimension : un service sans acte reste visible, à zéro.
WITH actes AS
(
    SELECT
        service_code,
        count()             AS nb_actes,
        uniqExact(stay_id)  AS nb_sejours_avec_acte,
        sum(montant_euros)  AS montant_facture_euros
    FROM {{ ref('fact_acte') }}
    GROUP BY service_code
)
SELECT
    d.service_code                      AS service_code,
    d.service_label                     AS service_label,
    d.capacite_lits                     AS capacite_lits,
    a.nb_actes                          AS nb_actes,
    a.nb_sejours_avec_acte              AS nb_sejours_avec_acte,
    ifNull(a.montant_facture_euros, 0)  AS montant_facture_euros
FROM {{ ref('dim_service') }} AS d
LEFT JOIN actes AS a USING (service_code)
