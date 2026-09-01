{{ config(order_by='(jour, service_code)') }}
-- Activité quotidienne par service : entrées, sorties, décès, séjours ouverts.
--
-- `sejours_en_cours` = séjours ouverts à la fin de la journée considérée : c'est la
-- charge réelle du service, invisible dans un simple comptage d'admissions.
--
-- Le calcul se fait par **balayage cumulé** du calendrier, et non en confrontant chaque
-- jour à chaque séjour. Un séjour pèse +1 à partir de son admission et −1 à partir de sa
-- sortie ; les séjours ouverts d'un jour sont donc la somme des entrées moins la somme
-- des sorties jusqu'à ce jour. Strictement équivalent au comptage
-- `admission <= jour AND (sortie IS NULL OR sortie > jour)`, mais le coût passe de
-- O(jours × séjours) — quadratique avec l'historique — à O(séjours) pour l'agrégation,
-- puis O(jours × services) pour le cumul.
WITH
-- Les mouvements, comptés une seule fois par (service, jour).
evenements AS
(
    SELECT service_code, admission_date AS jour,
           count() AS admissions, 0 AS sorties, 0 AS deces
    FROM {{ ref('fact_sejour') }}
    GROUP BY service_code, jour

    UNION ALL

    SELECT service_code, assumeNotNull(discharge_date) AS jour,
           0 AS admissions, count() AS sorties, countIf(is_deces) AS deces
    FROM {{ ref('fact_sejour') }}
    WHERE discharge_date IS NOT NULL
    GROUP BY service_code, jour
),
par_jour AS
(
    SELECT service_code, jour,
           sum(admissions) AS admissions, sum(sorties) AS sorties, sum(deces) AS deces
    FROM evenements
    GROUP BY service_code, jour
),
-- Le cumul exige une ligne par jour même sans mouvement : un service peut n'avoir ni
-- entrée ni sortie tout en gardant des patients hospitalisés.
grille AS
(
    SELECT c.jour AS jour, s.service_code AS service_code
    FROM (SELECT DISTINCT jour FROM par_jour) AS c
    CROSS JOIN (SELECT DISTINCT service_code FROM par_jour) AS s
),
quotidien AS
(
    SELECT
        g.jour                  AS jour,
        g.service_code          AS service_code,
        ifNull(e.admissions, 0) AS admissions,
        ifNull(e.sorties, 0)    AS sorties,
        ifNull(e.deces, 0)      AS deces
    FROM grille AS g
    LEFT JOIN par_jour AS e ON e.service_code = g.service_code AND e.jour = g.jour
)
SELECT
    q.jour             AS jour,
    q.service_code     AS service_code,
    d.service_label    AS service_label,
    q.admissions       AS admissions,
    q.sorties          AS sorties,
    q.deces            AS deces,
    q.sejours_en_cours AS sejours_en_cours
FROM
(
    SELECT
        jour, service_code, admissions, sorties, deces,
        toInt64(sum(admissions) OVER w) - toInt64(sum(sorties) OVER w) AS sejours_en_cours
    FROM quotidien
    WINDOW w AS (PARTITION BY service_code ORDER BY jour
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
) AS q
INNER JOIN {{ ref('dim_service') }} AS d ON d.service_code = q.service_code
-- Le filtre se fait ici et non en HAVING : `sejours_en_cours` est une fonction de
-- fenêtrage, elle n'existe pas encore au moment de l'agrégation.
WHERE q.admissions + q.sorties + q.sejours_en_cours > 0
