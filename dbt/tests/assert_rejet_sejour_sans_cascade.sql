-- Un rejet ne vaut que pour la table où vit l'anomalie.
--
-- Les séjours écartés par Q2 ont des horodatages inexploitables — mais leurs
-- diagnostics restent des faits cliniques et leurs relevés de constantes portent leur
-- propre horodatage. Les écarter en cascade minorerait la prévalence et perdrait des
-- centaines de relevés valides ; c'est exactement le défaut que ce contrôle interdit
-- de réintroduire.
--
-- Le test échoue si un séjour rejeté a perdu des diagnostics présents à la source.
SELECT
    r.stay_id                                          AS stay_id,
    uniqExact(b.code_cim10)                            AS diagnostics_deposes,
    uniqExactIf(f.code_cim10, f.code_cim10 != '')      AS diagnostics_conserves
FROM {{ ref('sejours_rejets') }} AS r
INNER JOIN {{ source('bronze', 'diagnostics') }} AS b USING (stay_id)
LEFT JOIN  {{ ref('fact_diagnostic') }} AS f
       ON  f.stay_id = r.stay_id AND f.code_cim10 = b.code_cim10
GROUP BY r.stay_id
HAVING diagnostics_conserves != diagnostics_deposes
