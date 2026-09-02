{{ config(order_by='(sexe, tranche_age_debut)') }}
-- Pyramide des âges de l'ensemble de la population suivie.
-- Grain : sexe × tranche d'âge, un patient compté UNE fois.
--
-- Cette table existe précisément parce que `nb_patients` est une mesure **non
-- additive** : sommer `cohorte_demographie` à travers les pathologies compterait
-- cinq fois un patient portant cinq diagnostics. La distribution d'ensemble doit donc
-- être calculée à son propre grain, jamais dérivée d'une autre table.
--
-- k-anonymat appliqué comme ailleurs : la cellule reste, l'effectif est masqué.
SELECT
    sexe,
    tranche_age_debut,
    tranche_age,
    nb >= {{ var('seuil_k') }}  AS diffusable,
    if(diffusable, nb, NULL)    AS nb_patients
FROM
(
    SELECT
        p.sex                                       AS sexe,
        {{ tranche_age_debut('p.birth_year') }}     AS tranche_age_debut,
        {{ tranche_age_libelle('p.birth_year') }}   AS tranche_age,
        uniqExact(p.patient_pseudo)                 AS nb
    FROM {{ ref('dim_patient') }} AS p
    GROUP BY sexe, tranche_age_debut, tranche_age
)
