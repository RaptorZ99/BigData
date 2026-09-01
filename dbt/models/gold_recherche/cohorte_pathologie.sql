{{ config(order_by='code_cim10') }}
-- Taille des cohortes par diagnostic CIM-10.
--
-- Trois garde-fous RGPD s'appliquent à TOUTES les tables de cette base :
--   1. agrégats uniquement — aucune ligne patient n'est exposée ;
--   2. k-anonymat : chaque cellule diffusée regroupe au moins `seuil_k` patients ;
--   3. âges diffusés en tranches de 10 ans, jamais en valeur exacte.
SELECT
    d.code_cim10                                        AS code_cim10,
    c.libelle                                           AS libelle,
    uniqExact(d.patient_pseudo)                         AS nb_patients,
    uniqExactIf(d.patient_pseudo, d.is_principal)       AS nb_patients_diag_principal,
    uniqExact(d.stay_id)                                AS nb_sejours,
    countIf(d.is_principal)                             AS nb_diagnostics_principaux,
    countIf(NOT d.is_principal)                         AS nb_diagnostics_associes
FROM {{ ref('fact_diagnostic') }} AS d
INNER JOIN {{ ref('dim_cim10') }} AS c USING (code_cim10)
GROUP BY code_cim10, libelle
HAVING nb_patients >= {{ var('seuil_k') }}
