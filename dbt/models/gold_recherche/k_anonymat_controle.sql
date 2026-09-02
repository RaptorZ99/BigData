{{ config(order_by='table_cible') }}
-- Preuve du dispositif, volontairement diffusable.
--
-- Elle dit combien de cellules ont été masquées et sur quel critère, sans jamais
-- révéler lesquelles ni leur effectif. C'est ce qui permet à un chercheur — ou à un
-- auditeur — de constater que le seuil est réellement appliqué, sans lui donner le
-- moindre moyen de le contourner.
--
-- Les compteurs sont typés explicitement en Int64 dans toutes les branches. Sans cela,
-- ClickHouse réconcilie `countIf` (UInt64) et une soustraction (Int64) en un
-- `Variant(Int64, UInt64)` : un type exotique sur lequel un simple `sum()` échoue avec
-- ILLEGAL_TYPE_OF_ARGUMENT. La table est diffusée aux chercheurs, elle doit se
-- manipuler comme n'importe quelle autre.
SELECT
    'prevalence_pathologie'          AS table_cible,
    'cohorte de moins de {{ var("seuil_k") }} patients' AS motif,
    toInt64(count())                 AS cellules_calculees,
    toInt64(countIf(diffusable))     AS cellules_diffusees,
    toInt64(countIf(NOT diffusable)) AS cellules_masquees,
    toUInt8({{ var('seuil_k') }})    AS seuil_k
FROM {{ ref('prevalence_pathologie') }}

UNION ALL

SELECT
    'cohorte_demographie',
    'cellule pathologie × tranche d''âge × sexe de moins de {{ var("seuil_k") }} patients',
    toInt64(count()),
    toInt64(countIf(diffusable)),
    toInt64(countIf(NOT diffusable)),
    toUInt8({{ var('seuil_k') }})
FROM {{ ref('cohorte_demographie') }}

UNION ALL

SELECT
    'cohorte_demographie_globale',
    'cellule tranche d''âge × sexe de moins de {{ var("seuil_k") }} patients',
    toInt64(count()),
    toInt64(countIf(diffusable)),
    toInt64(countIf(NOT diffusable)),
    toUInt8({{ var('seuil_k') }})
FROM {{ ref('cohorte_demographie_globale') }}
