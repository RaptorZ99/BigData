-- La répartition par sexe lisible dans `cohorte_demographie` doit être EXACTE.
--
-- Le tableau de bord recherche en tire une « part de femmes » par pathologie, en
-- sommant les tranches d'âge. Cette somme n'est légitime que si aucune cellule de la
-- pathologie n'a été masquée (cf. `assert_pas_de_suppression_partielle`). Ce test
-- vérifie le résultat plutôt que la condition : il compare la part publiée à celle
-- recalculée depuis silver, pathologie par pathologie, et n'admet aucun écart.
WITH publiee AS (
    SELECT code_cim10,
           round(100.0 * sumIf(nb_patients, sexe = 'F') / sum(nb_patients), 1) AS pct
    FROM {{ ref('cohorte_demographie') }}
    WHERE diffusable
    GROUP BY code_cim10
),
reelle AS (
    SELECT d.code_cim10 AS code_cim10,
           round(100.0 * uniqExactIf(d.patient_pseudo, p.sex = 'F')
                       / uniqExact(d.patient_pseudo), 1) AS pct
    FROM {{ ref('fact_diagnostic') }} AS d
    INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
    WHERE d.is_principal
    GROUP BY code_cim10
)
SELECT publiee.code_cim10, publiee.pct AS pct_publie, reelle.pct AS pct_reel
FROM publiee INNER JOIN reelle USING (code_cim10)
WHERE abs(publiee.pct - reelle.pct) > 0.05
