-- Le drapeau `diffusable` et l'effectif doivent dire la même chose : une cellule
-- diffusable porte un effectif, une cellule masquée n'en porte aucun.
--
-- Sans ce contrôle, une erreur d'écriture pourrait publier un effectif sous le seuil
-- tout en l'annonçant comme masqué — ou l'inverse, retirer une valeur parfaitement
-- diffusable sans que personne ne s'en aperçoive.
{% set tables = ['prevalence_pathologie', 'cohorte_demographie', 'cohorte_demographie_globale'] %}
{% for t in tables %}
SELECT '{{ t }}' AS table_cible, diffusable, nb_patients
FROM {{ ref(t) }}
WHERE diffusable != (nb_patients IS NOT NULL)
{% if not loop.last %}UNION ALL{% endif %}
{% endfor %}
