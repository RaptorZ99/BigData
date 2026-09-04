{{ config(order_by='rang') }}
-- KPI évolution 4 — Densité d'actes par lit : nb_actes / capacite_lits.
--
-- Grain : le service. Mesure l'intensité du plateau technique : combien d'actes chaque
-- lit a « produits » sur la période. Agrégation reprise de `int_actes_service`.
--
-- `actes_par_lit` est NULL quand la capacité l'est : on ne divise pas par un nombre de
-- lits qu'on ne connaît pas. Le service non décrit (NEURO) garde donc sa ligne et ses
-- actes, sans densité — ni 0, ni infinie, ni inventée. Il se classe en dernier.
--
-- `rang` classe les services du plateau le plus dense au moins dense ; clé de tri
-- physique de la table.
SELECT
    service_code,
    service_label,
    capacite_lits,
    nb_actes,
    actes_par_lit,
    row_number() OVER (ORDER BY actes_par_lit DESC NULLS LAST, service_code) AS rang
FROM
(
    SELECT
        service_code,
        service_label,
        capacite_lits,
        nb_actes,
        round(nb_actes / capacite_lits, 1) AS actes_par_lit
    FROM {{ ref('int_actes_service') }}
)
