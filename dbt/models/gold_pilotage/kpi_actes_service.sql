{{ config(order_by='rang') }}
-- KPI évolution 2 — Nombre d'actes par service, et nombre moyen d'actes par séjour.
--
-- Grain : le service. L'agrégation est écrite une fois, dans `int_actes_service` (le
-- fait agrégé seul, puis joint sur sa dimension) ; cette table ne fait qu'en publier
-- la lecture demandée.
--
-- `actes_par_sejour` rapporte les actes aux séjours qui en ont au moins un : c'est
-- l'intensité de prise en charge d'un séjour traité, pas une moyenne diluée sur les
-- séjours sans acte. NULL — et non 0 — pour un service sans aucun acte : le ratio n'y
-- est pas défini.
--
-- `rang` classe les services du plus au moins actif ; clé de tri physique de la table.
SELECT
    service_code,
    service_label,
    nb_actes,
    nb_sejours_avec_acte,
    if(nb_sejours_avec_acte = 0, NULL, round(nb_actes / nb_sejours_avec_acte, 2)) AS actes_par_sejour,
    row_number() OVER (ORDER BY nb_actes DESC, service_code)                       AS rang
FROM {{ ref('int_actes_service') }}
