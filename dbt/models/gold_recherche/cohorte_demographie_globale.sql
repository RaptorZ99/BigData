{{ config(order_by='(sexe, tranche_age_debut)') }}
-- Pyramide des âges de l'ensemble de la population suivie.
-- Grain : sexe × tranche d'âge, un patient compté UNE fois.
--
-- Cette table existe précisément parce que `nb_patients` est une mesure **non
-- additive** : la sommer à travers les pathologies compterait cinq fois un patient
-- portant cinq diagnostics. La distribution d'ensemble doit donc être calculée à son
-- propre grain, jamais dérivée de `cohorte_demographie`.
SELECT
    p.sex                                       AS sexe,
    {{ tranche_age_debut('p.birth_year') }}     AS tranche_age_debut,
    {{ tranche_age_libelle('p.birth_year') }}   AS tranche_age,
    uniqExact(s.patient_pseudo)                 AS nb_patients
FROM {{ ref('fact_sejour') }} AS s
INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
GROUP BY sexe, tranche_age_debut, tranche_age
HAVING nb_patients >= {{ var('seuil_k') }}
