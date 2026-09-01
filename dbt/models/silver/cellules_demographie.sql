{{ config(order_by='(code_cim10, sexe, tranche_age_debut, region_code)') }}
-- Travail interne du k-anonymat : le grain fin AVEC les effectifs sous le seuil.
--
-- ⚠ Cette table vit dans `eds_silver`, PAS dans la base des chercheurs : elle contient
-- précisément ce que le k-anonymat doit cacher. La placer dans `eds_gold_recherche`
-- exposerait directement ce que la suppression complémentaire protège.
--
-- Elle encode une règle de **diffusion** et non de qualité, mais elle est rangée là où
-- les comptes de restitution n'ont aucun droit.
SELECT
    d.code_cim10                                                    AS code_cim10,
    c.libelle                                                       AS libelle,
    p.region_code                                                   AS region_code,
    p.sex                                                           AS sexe,
    {{ tranche_age_debut('p.birth_year') }}                         AS tranche_age_debut,
    {{ tranche_age_libelle('p.birth_year') }}                       AS tranche_age,
    uniqExact(d.patient_pseudo)                                     AS nb_patients,
    uniqExact(d.patient_pseudo) >= {{ var('seuil_k') }}             AS diffusable
FROM {{ ref('fact_diagnostic') }} AS d
INNER JOIN {{ ref('dim_cim10') }}   AS c USING (code_cim10)
INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
GROUP BY code_cim10, libelle, region_code, sexe, tranche_age_debut, tranche_age
