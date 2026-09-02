-- La répartition par sexe diffusée doit être EXACTE, pas approchée.
--
-- Sommer `cohorte_demographie` à travers les tranches d'âge donnerait un ratio calculé
-- sur les seules cellules ayant survécu au seuil : un biais de plusieurs points, sans
-- que rien ne le signale. Ce test compare la part de femmes publiée à celle de la
-- couche silver, pathologie par pathologie, et n'admet aucun écart.
WITH publiee AS (
    SELECT code_cim10,
           round(100.0 * sumIf(nb_patients, sexe = 'F') / sum(nb_patients), 1) AS pct
    FROM {{ ref('cohorte_demographie_sexe') }}
    GROUP BY code_cim10
),
reelle AS (
    SELECT d.code_cim10 AS code_cim10,
           round(100.0 * uniqExactIf(d.patient_pseudo, p.sex = 'F')
                       / uniqExact(d.patient_pseudo), 1) AS pct
    FROM {{ ref('fact_diagnostic') }} AS d
    INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
    GROUP BY code_cim10
)
SELECT publiee.code_cim10, publiee.pct AS pct_publie, reelle.pct AS pct_reel
FROM publiee INNER JOIN reelle USING (code_cim10)
WHERE abs(publiee.pct - reelle.pct) > 0.05
