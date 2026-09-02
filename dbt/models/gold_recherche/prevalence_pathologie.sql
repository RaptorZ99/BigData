{{ config(order_by='code_cim10') }}
-- KPI 5 — Prévalence par pathologie : taille des cohortes par diagnostic CIM-10.
--
-- Un patient est compté une fois par pathologie, quel que soit son nombre de séjours
-- et le rang du diagnostic (principal ou associé) : c'est la définition
-- épidémiologique de la prévalence.
--
-- ⚠ `nb_patients` est une mesure NON additive. La sommer à travers les pathologies
-- compterait cinq fois un patient portant cinq diagnostics. Le dénominateur est donc
-- calculé séparément, comme un scalaire agrégé sur `dim_patient` — jamais par
-- jointure entre deux tables de faits.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  k-anonymat : masquer plutôt que supprimer
--
--  Une cohorte de moins de `seuil_k` patients ne peut pas être diffusée. Sa ligne
--  reste néanmoins présente, effectifs à NULL et `diffusable` à faux.
--
--  Faire disparaître la ligne serait moins protecteur, pas plus : le chercheur ne
--  saurait pas qu'une valeur a été retirée, et le dispositif de protection ne serait
--  vérifiable nulle part. C'est la pratique du contrôle statistique de la divulgation
--  (les instituts publient la cellule marquée « secret », ils ne la retirent pas).
--  Ce qui est protégé, c'est l'effectif — et il ne sort pas d'ici.
-- ═══════════════════════════════════════════════════════════════════════════
WITH (SELECT count() FROM {{ ref('dim_patient') }}) AS population
SELECT
    code_cim10,
    libelle,
    nb >= {{ var('seuil_k') }}                                      AS diffusable,
    if(diffusable, nb, NULL)                                        AS nb_patients,
    if(diffusable, nb_sejours, NULL)                                AS nb_sejours,
    if(diffusable, round(100.0 * nb / population, 2), NULL)         AS prevalence_pct,
    population                                                      AS nb_patients_total
FROM
(
    SELECT
        d.code_cim10                AS code_cim10,
        c.libelle                   AS libelle,
        uniqExact(d.patient_pseudo) AS nb,
        uniqExact(d.stay_id)        AS nb_sejours
    FROM {{ ref('fact_diagnostic') }} AS d
    INNER JOIN {{ ref('dim_cim10') }} AS c USING (code_cim10)
    GROUP BY code_cim10, libelle
)
