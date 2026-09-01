{{ config(order_by='admission_date') }}
-- Activité quotidienne des urgences.
--
-- Deux lectures coexistent et ne donnent pas le même chiffre ; on expose les deux
-- plutôt que d'en imposer une :
--   * passages par le service URGENCES (unité d'hospitalisation) ;
--   * admissions en mode « urgence », tous services confondus (mode d'entrée).
SELECT
    admission_date                                  AS admission_date,
    countIf(is_service_urgences)                    AS nb_passages_service_urgences,
    countIf(is_admission_urgence)                   AS nb_admissions_mode_urgence,
    count()                                         AS nb_admissions_total,
    round(100.0 * countIf(is_admission_urgence) / count(), 1) AS pct_admissions_urgence
FROM {{ ref('fact_sejour') }}
GROUP BY admission_date
