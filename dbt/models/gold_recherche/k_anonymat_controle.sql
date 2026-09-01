{{ config(order_by='table_cible') }}
-- Preuve du dispositif, volontairement diffusable.
--
-- Elle dit combien de cellules ont été retirées et pourquoi, sans jamais révéler
-- lesquelles ni leur effectif. Depuis la suppression complémentaire, connaître ces
-- nombres n'aide plus à retrouver quoi que ce soit : les marges correspondantes ont
-- disparu elles aussi.
--
-- Les compteurs sont typés explicitement en Int64 dans les DEUX branches. Sans cela,
-- ClickHouse réconcilie `countIf` (UInt64) et une soustraction (Int64) en un
-- `Variant(Int64, UInt64)` : un type exotique sur lequel un simple `sum()` échoue avec
-- ILLEGAL_TYPE_OF_ARGUMENT. La table est diffusée aux chercheurs, elle doit se
-- manipuler comme n'importe quelle autre.
SELECT
    'cohorte_demographie_region'     AS table_cible,
    'seuil k >= {{ var("seuil_k") }}' AS motif,
    toInt64(count())                 AS cellules_calculees,
    toInt64(countIf(diffusable))     AS cellules_diffusees,
    toInt64(countIf(NOT diffusable)) AS cellules_supprimees,
    toUInt8({{ var('seuil_k') }})    AS seuil_k
FROM {{ ref('cellules_demographie') }}

UNION ALL

SELECT
    'cohorte_demographie',
    'suppression complémentaire (décomposition incomplète)',
    toInt64(uniqExact((code_cim10, sexe, tranche_age_debut))),
    -- `ifNull` : une sous-requête scalaire est Nullable par construction, et un
    -- compteur qui peut valoir NULL n'a pas de sens ici — la table source est bâtie
    -- juste au-dessus, elle ne peut pas manquer.
    ifNull(toInt64((SELECT count() FROM {{ ref('cohorte_demographie') }})), 0),
    toInt64(uniqExact((code_cim10, sexe, tranche_age_debut)))
        - ifNull(toInt64((SELECT count() FROM {{ ref('cohorte_demographie') }})), 0),
    toUInt8({{ var('seuil_k') }})
FROM {{ ref('cellules_demographie') }}
