-- Aucun effectif diffusé ne doit décrire moins de `seuil_k` patients.
-- Le contrôle couvre les trois tables de la base recherche qui portent un effectif.
--
-- Les cellules sous le seuil restent publiées, effectif à NULL : le test vérifie donc
-- qu'aucune valeur NON NULLE ne passe sous le seuil. Un `nb_patients` renseigné et
-- inférieur à k serait une fuite.
{% set tables = ['prevalence_pathologie', 'cohorte_demographie', 'cohorte_demographie_globale'] %}
{% for t in tables %}
SELECT '{{ t }}' AS table_cible, nb_patients
FROM {{ ref(t) }}
WHERE nb_patients IS NOT NULL AND nb_patients < {{ var('seuil_k') }}
{% if not loop.last %}UNION ALL{% endif %}
{% endfor %}
