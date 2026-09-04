{{ config(order_by='rang') }}
-- KPI évolution 1 — Activité et DMS par catégorie de service (séjours clos).
--
-- Grain : la catégorie, niveau intermédiaire de la hiérarchie service → catégorie → pôle
-- portée par `dim_service`. Même définition que la DMS par service (KPI 1 historique) :
-- seuls les séjours terminés comptent, pour l'effectif comme pour la durée — un séjour
-- en cours n'a pas de durée, et le compter avec sa durée partielle tirerait la moyenne
-- vers le bas.
--
-- Le service non décrit (NEURO) apparaît sous la catégorie « (non decrit) » : ses
-- séjours existent, les faire disparaître de l'activité serait un mensonge par
-- omission. La ligne dit exactement ce qu'elle est.
--
-- Pas de colonne `pole` ici : dans le référentiel déposé, une catégorie peut relever de
-- deux pôles (« medecine » est en Coeur-Poumon ET en Cancerologie). Le pôle est une
-- propriété du service, pas de la catégorie — il ne peut donc pas figurer à ce grain.
--
-- `rang` classe les catégories de la plus active à la moins active ; c'est aussi la clé
-- de tri physique de la table, qui se lit donc dans cet ordre sans ORDER BY.
SELECT
    categorie,
    nb_sejours,
    dms_jours,
    row_number() OVER (ORDER BY nb_sejours DESC, categorie) AS rang
FROM
(
    SELECT
        d.categorie                     AS categorie,
        count()                         AS nb_sejours,
        round(avg(f.duree_jours), 2)    AS dms_jours
    FROM {{ ref('fact_sejour') }} AS f
    INNER JOIN {{ ref('dim_service') }} AS d USING (service_code)
    WHERE f.discharge_ts IS NOT NULL
    GROUP BY categorie
)
