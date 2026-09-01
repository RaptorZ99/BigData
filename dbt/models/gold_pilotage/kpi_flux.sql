{{ config(order_by='(jour, sens, mode)') }}
-- Répartition quotidienne des modes d'admission et de sortie.
-- Format long (jour × sens × mode) : directement exploitable en barres empilées.
SELECT
    admission_date AS jour,
    'admission'    AS sens,
    admission_mode AS mode,
    count()        AS nb_sejours
FROM {{ ref('fact_sejour') }}
GROUP BY jour, sens, mode

UNION ALL

SELECT
    assumeNotNull(discharge_date)           AS jour,
    'sortie'                                AS sens,
    ifNull(discharge_mode, 'non renseigne') AS mode,
    count()                                 AS nb_sejours
FROM {{ ref('fact_sejour') }}
WHERE discharge_date IS NOT NULL
GROUP BY jour, sens, mode
