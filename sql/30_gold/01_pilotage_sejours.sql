-- Gold pilotage — indicateurs bâtis sur l'étoile fact_sejour.
-- Toutes les tables sont des agrégats : aucune ligne patient n'est exposée.

-- ── Durée Moyenne de Séjour par service ─────────────────────────────────────
-- Seuls les séjours terminés entrent dans la moyenne : compter un séjour en
-- cours avec sa durée partielle tirerait la DMS vers le bas.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_dms_service
ENGINE = MergeTree
ORDER BY (service_code, discharge_date)
COMMENT 'DMS par service et jour de sortie (séjours terminés uniquement)'
AS
SELECT
    f.service_code                       AS service_code,
    d.service_label                      AS service_label,
    -- Le filtre WHERE garantit une date de sortie : on lève le caractère
    -- nullable pour pouvoir l'utiliser comme clé de tri.
    assumeNotNull(f.discharge_date)      AS discharge_date,
    count()                              AS nb_sorties,
    round(avg(f.duree_jours), 2)         AS dms_jours,
    round(median(f.duree_jours), 2)      AS duree_mediane_jours,
    round(min(f.duree_jours), 2)         AS duree_min_jours,
    round(max(f.duree_jours), 2)         AS duree_max_jours
FROM eds_silver.fact_sejour AS f
INNER JOIN eds_silver.dim_service AS d USING (service_code)
WHERE f.discharge_ts IS NOT NULL
GROUP BY service_code, service_label, discharge_date;

-- ── Activité des urgences ───────────────────────────────────────────────────
-- Deux lectures coexistent et ne donnent pas le même chiffre ; on expose les
-- deux plutôt que d'en imposer une :
--   * passages par le service URGENCES (unité d'hospitalisation) ;
--   * admissions en mode « urgence », tous services confondus (mode d'entrée).
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_urgences_jour
ENGINE = MergeTree
ORDER BY admission_date
COMMENT 'Activité quotidienne des urgences : deux définitions, exposées côte à côte'
AS
SELECT
    admission_date                                  AS admission_date,
    countIf(is_service_urgences)                    AS nb_passages_service_urgences,
    countIf(is_admission_urgence)                   AS nb_admissions_mode_urgence,
    count()                                         AS nb_admissions_total,
    round(100.0 * countIf(is_admission_urgence) / count(), 1) AS pct_admissions_urgence
FROM eds_silver.fact_sejour
GROUP BY admission_date;

-- ── Réadmissions à 30 jours ─────────────────────────────────────────────────
-- Définition retenue : un séjour est suivi d'une réadmission s'il existe, pour
-- le même patient, **une** admission postérieure à la sortie et survenant dans
-- les 30 jours qui suivent.
--
-- On teste l'ensemble des admissions du patient, et non la seule admission
-- chronologiquement suivante : ces données comportent beaucoup de séjours qui
-- se chevauchent, si bien que l'admission « suivante » est souvent un séjour
-- concurrent commencé avant la sortie — il masquerait la réadmission réelle.
--
-- Dénominateur : sorties vivantes uniquement — un patient décédé ne peut pas
-- être réadmis, l'inclure minorerait artificiellement le taux.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_readmissions_30j
ENGINE = MergeTree
ORDER BY (service_code, discharge_date)
COMMENT 'Taux de réadmission à 30 jours par service et jour de sortie (indicateur qualité des soins)'
AS
WITH sejours_avec_historique AS
(
    SELECT
        service_code,
        discharge_ts,
        discharge_date,
        discharge_mode,
        -- Toutes les admissions du patient (au plus une dizaine par patient).
        groupArray(admission_ts) OVER (PARTITION BY patient_pseudo) AS admissions_du_patient
    FROM eds_silver.fact_sejour
),
eligibles AS
(
    SELECT
        service_code,
        assumeNotNull(discharge_date) AS discharge_date,
        arrayExists(
            adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY,
            admissions_du_patient
        ) AS est_readmis
    FROM sejours_avec_historique
    WHERE discharge_ts IS NOT NULL
      AND (discharge_mode IS NULL OR discharge_mode != 'deces')
)
SELECT
    e.service_code                                          AS service_code,
    d.service_label                                         AS service_label,
    e.discharge_date                                        AS discharge_date,
    count()                                                 AS sorties_eligibles,
    countIf(e.est_readmis)                                  AS readmissions_30j,
    round(100.0 * countIf(e.est_readmis) / count(), 1)      AS taux_readmission_pct
FROM eligibles AS e
INNER JOIN eds_silver.dim_service AS d ON d.service_code = e.service_code
GROUP BY service_code, service_label, discharge_date;

-- ── Activité par service ────────────────────────────────────────────────────
-- `en_cours` = séjours ouverts à la fin de la journée considérée : c'est la
-- charge réelle du service, invisible dans un simple comptage d'admissions.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_activite_service
ENGINE = MergeTree
ORDER BY (jour, service_code)
COMMENT 'Activité quotidienne par service : entrées, sorties, décès, séjours ouverts'
AS
WITH calendrier AS
(
    SELECT DISTINCT jour
    FROM
    (
        SELECT admission_date AS jour FROM eds_silver.fact_sejour
        UNION DISTINCT
        SELECT assumeNotNull(discharge_date) AS jour
        FROM eds_silver.fact_sejour
        WHERE discharge_date IS NOT NULL
    )
)
SELECT
    c.jour                                                          AS jour,
    f.service_code                                                  AS service_code,
    d.service_label                                                 AS service_label,
    countIf(f.admission_date = c.jour)                              AS admissions,
    countIf(f.discharge_date = c.jour)                              AS sorties,
    countIf(f.discharge_date = c.jour AND f.is_deces)               AS deces,
    countIf(
        f.admission_date <= c.jour
        AND (f.discharge_date IS NULL OR f.discharge_date > c.jour)
    )                                                               AS sejours_en_cours
FROM calendrier AS c
CROSS JOIN eds_silver.fact_sejour AS f
INNER JOIN eds_silver.dim_service AS d ON d.service_code = f.service_code
GROUP BY jour, service_code, service_label
HAVING admissions + sorties + sejours_en_cours > 0;

-- ── Flux d'entrée et de sortie ──────────────────────────────────────────────
-- Format long (jour × sens × mode) : directement exploitable en barres empilées.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_flux
ENGINE = MergeTree
ORDER BY (jour, sens, mode)
COMMENT 'Répartition quotidienne des modes d''admission et de sortie'
AS
SELECT
    admission_date AS jour,
    'admission'    AS sens,
    admission_mode AS mode,
    count()        AS nb_sejours
FROM eds_silver.fact_sejour
GROUP BY jour, sens, mode

UNION ALL

SELECT
    assumeNotNull(discharge_date)           AS jour,
    'sortie'                                AS sens,
    ifNull(discharge_mode, 'non renseigne') AS mode,
    count()                                 AS nb_sejours
FROM eds_silver.fact_sejour
WHERE discharge_date IS NOT NULL
GROUP BY jour, sens, mode;
