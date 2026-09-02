{{ config(order_by='categorie') }}
-- KPI évolution 1 — Activité et DMS par catégorie de service.
--
-- Grain : la catégorie, niveau intermédiaire de la hiérarchie service → catégorie → pôle
-- portée par `dim_service`. Même définition que la DMS par service : séjours terminés
-- uniquement pour la durée, tous les séjours valides pour l'activité.
--
-- Le service non décrit (NEURO) apparaît sous la catégorie « non renseigne » : ses
-- 1 208 séjours existent, les faire disparaître de l'activité serait un mensonge par
-- omission. La ligne dit exactement ce qu'elle est.
--
-- Pas de colonne `pole` ici : dans le référentiel déposé, une catégorie peut relever de
-- deux pôles (« medecine » est en Coeur-Poumon ET en Cancerologie). Le pôle est une
-- propriété du service, pas de la catégorie — il ne peut donc pas figurer à ce grain.
SELECT
    d.categorie                                                 AS categorie,
    uniqExact(f.service_code)                                   AS nb_services,
    count()                                                     AS nb_sejours,
    countIf(f.discharge_ts IS NOT NULL)                         AS nb_sejours_termines,
    countIf(f.is_ongoing)                                       AS nb_sejours_en_cours,
    round(avgIf(f.duree_jours,  f.discharge_ts IS NOT NULL), 2) AS dms_jours,
    round(avgIf(f.duree_heures, f.discharge_ts IS NOT NULL), 1) AS dms_heures
FROM {{ ref('fact_sejour') }} AS f
INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
GROUP BY categorie
