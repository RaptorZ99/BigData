-- Aucune cellule diffusée ne doit regrouper moins de `seuil_k` patients.
-- Le test couvre les quatre tables de la base recherche qui portent un effectif.
SELECT 'cohorte_pathologie' AS table_cible, nb_patients
FROM {{ ref('cohorte_pathologie') }}          WHERE nb_patients < {{ var('seuil_k') }}
UNION ALL
SELECT 'prevalence_pathologie', nb_patients
FROM {{ ref('prevalence_pathologie') }}       WHERE nb_patients < {{ var('seuil_k') }}
UNION ALL
SELECT 'cohorte_demographie', nb_patients
FROM {{ ref('cohorte_demographie') }}         WHERE nb_patients < {{ var('seuil_k') }}
UNION ALL
SELECT 'cohorte_demographie_region', nb_patients
FROM {{ ref('cohorte_demographie_region') }}  WHERE nb_patients < {{ var('seuil_k') }}
UNION ALL
SELECT 'cohorte_demographie_globale', nb_patients
FROM {{ ref('cohorte_demographie_globale') }} WHERE nb_patients < {{ var('seuil_k') }}
