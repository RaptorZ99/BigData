{{ config(order_by='service_code') }}
-- KPI évolution 2, 4 et 5 — Actes par service, densité par lit, montant facturé (T2A).
--
-- Un seul grain, le service, donc une seule table pour trois indicateurs : les publier
-- séparément recopierait trois fois la même agrégation et finirait par diverger.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  « Actes par séjour » sans relier deux tables de faits
--
--  Le nombre d'actes vient de fact_acte, le nombre de séjours de fact_sejour. Les
--  joindre ligne à ligne multiplierait chaque séjour par ses actes et gonflerait tous
--  les comptages. C'est le motif classique du *drill-across* de Kimball : chaque fait
--  est d'abord agrégé SEUL au grain de la dimension conformée (le service), puis les
--  deux agrégats — huit lignes chacun — se rejoignent sur `dim_service`. Aucune ligne
--  de fait ne rencontre jamais une ligne de l'autre fait.
--
--  Le test `assert_actes_reconcilies` est le garde-fou : la somme des actes de cette
--  table doit valoir exactement le nombre de lignes de fact_acte. Une jointure
--  fait-à-fait le ferait exploser.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Dénominateurs, pour être exact :
--   * `nb_sejours` compte les séjours VALIDES du service (fact_sejour, 6 729 au total) ;
--   * `nb_actes` compte tous les actes rattachables, y compris les 82 réalisés pendant
--     les 68 séjours aux horodatages incohérents — un acte est un fait clinique, le
--     séjour écarté ne l'annule pas (même règle que les diagnostics et les relevés).
--   * `actes_par_lit` est NULL quand la capacité l'est : on ne divise pas par un
--     nombre de lits qu'on ne connaît pas.
WITH actes AS
(
    SELECT
        service_code,
        count()                     AS nb_actes,
        uniqExact(stay_id)          AS nb_sejours_avec_acte,
        sum(montant_euros)          AS montant_facture_euros
    FROM {{ ref('fact_acte') }}
    GROUP BY service_code
),
sejours AS
(
    SELECT service_code, count() AS nb_sejours
    FROM {{ ref('fact_sejour') }}
    GROUP BY service_code
)
SELECT
    d.service_code                                              AS service_code,
    d.service_label                                             AS service_label,
    d.categorie                                                 AS categorie,
    d.capacite_lits                                             AS capacite_lits,
    s.nb_sejours                                                AS nb_sejours,
    a.nb_sejours_avec_acte                                      AS nb_sejours_avec_acte,
    a.nb_actes                                                  AS nb_actes,
    ifNotFinite(round(a.nb_actes / s.nb_sejours, 2), 0)         AS actes_par_sejour,
    round(a.nb_actes / d.capacite_lits, 1)                      AS actes_par_lit,
    ifNull(a.montant_facture_euros, 0)                          AS montant_facture_euros
FROM {{ ref('dim_service') }} AS d
LEFT JOIN actes   AS a USING (service_code)
LEFT JOIN sejours AS s USING (service_code)
