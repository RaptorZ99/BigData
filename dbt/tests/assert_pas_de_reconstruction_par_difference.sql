-- Le seuil seul ne suffit pas : publier une marge ET sa décomposition laisse retrouver
-- la cellule cachée par soustraction. Ce test rejoue l'attaque et exige qu'elle ne
-- rende rien — c'est la vérification de la suppression complémentaire.
SELECT m.code_cim10, m.sexe, m.tranche_age, m.nb_patients - sum(r.nb_patients) AS reste
FROM {{ ref('cohorte_demographie') }} AS m
LEFT JOIN {{ ref('cohorte_demographie_region') }} AS r
  ON  r.code_cim10  = m.code_cim10
  AND r.sexe        = m.sexe
  AND r.tranche_age = m.tranche_age
GROUP BY m.code_cim10, m.sexe, m.tranche_age, m.nb_patients
HAVING reste > 0
