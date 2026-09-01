-- « On écarte, on ne corrige pas » : une ligne rejetée sans motif serait une
-- suppression silencieuse.
SELECT 'sejours_rejets' AS table_cible, stay_id AS cle
FROM {{ ref('sejours_rejets') }}
WHERE reject_reason = '' OR reject_reason IS NULL

UNION ALL

SELECT 'monitoring_rejets', concat(stay_id, '@', toString(ts))
FROM {{ ref('monitoring_rejets') }}
WHERE reject_reason = '' OR reject_reason IS NULL
