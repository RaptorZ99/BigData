{{ config(order_by='code_cim10') }}
-- Prévalence : part des patients concernés par chaque pathologie.
--
-- Dénominateur : patients distincts ayant au moins un séjour. Il est calculé comme un
-- scalaire agrégé, jamais par jointure entre deux tables de faits.
WITH (SELECT uniqExact(patient_pseudo) FROM {{ ref('fact_sejour') }}) AS total_patients
SELECT
    d.code_cim10                                                       AS code_cim10,
    c.libelle                                                          AS libelle,
    uniqExact(d.patient_pseudo)                                        AS nb_patients,
    total_patients                                                     AS nb_patients_total,
    round(100.0 * uniqExact(d.patient_pseudo) / total_patients, 2)     AS prevalence_pct
FROM {{ ref('fact_diagnostic') }} AS d
INNER JOIN {{ ref('dim_cim10') }} AS c USING (code_cim10)
GROUP BY code_cim10, libelle
HAVING nb_patients >= {{ var('seuil_k') }}
