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
--
-- ⚠ FENÊTRE D'OBSERVATION — la limite majeure de cet indicateur.
--
-- Une réadmission ne peut être constatée que si l'entrepôt couvre la période où
-- elle surviendrait. Or les admissions s'arrêtent au dernier jour déposé, tandis
-- que les sorties s'étalent bien au-delà : une sortie postérieure à la dernière
-- admission connue a une probabilité **structurellement nulle** d'être suivie
-- d'une réadmission observable. Elle ne mesure donc rien, et l'agréger avec les
-- autres dilue mécaniquement le taux.
--
-- Chaque ligne porte pour cette raison `jours_observables` : le nombre de jours
-- de la fenêtre de 30 jours effectivement couverts par les données. Les
-- indicateurs de synthèse ne retiennent que les sorties dont la fenêtre est
-- non vide, et le tableau de bord affiche la couverture.
--
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
-- Dernière admission connue : au-delà, aucune réadmission n'est observable.
WITH (SELECT max(admission_date) FROM eds_silver.fact_sejour) AS derniere_admission
SELECT
    e.service_code                                          AS service_code,
    d.service_label                                         AS service_label,
    e.discharge_date                                        AS discharge_date,

    -- Part de la fenêtre de 30 jours réellement couverte par les données.
    -- Le « + 1 » compte le jour de sortie lui-même : une sortie le dernier jour
    -- déposé peut encore être suivie d'une réadmission quelques heures plus tard.
    -- 0 = la sortie est postérieure à la dernière admission connue : la ligne ne
    -- peut rien constater, et son taux de 0 % ne mesure rien.
    greatest(0, least(30, dateDiff('day', e.discharge_date, derniere_admission) + 1))
                                                            AS jours_observables,
    dateDiff('day', e.discharge_date, derniere_admission) + 1 >= 30
                                                            AS fenetre_complete,

    count()                                                 AS sorties_eligibles,
    countIf(e.est_readmis)                                  AS readmissions_30j,
    round(100.0 * countIf(e.est_readmis) / count(), 1)      AS taux_readmission_pct
FROM
(
    SELECT
        service_code,
        assumeNotNull(discharge_date) AS discharge_date,
        arrayExists(
            adm -> adm > discharge_ts AND adm <= discharge_ts + INTERVAL 30 DAY,
            admissions_du_patient
        ) AS est_readmis
    FROM
    (
        SELECT
            service_code,
            discharge_ts,
            discharge_date,
            discharge_mode,
            -- Toutes les admissions du patient (au plus une dizaine par patient).
            groupArray(admission_ts) OVER (PARTITION BY patient_pseudo)
                AS admissions_du_patient
        FROM eds_silver.fact_sejour
    )
    WHERE discharge_ts IS NOT NULL
      AND (discharge_mode IS NULL OR discharge_mode != 'deces')
) AS e
INNER JOIN eds_silver.dim_service AS d ON d.service_code = e.service_code
GROUP BY service_code, service_label, discharge_date, jours_observables, fenetre_complete;

-- ── Activité par service ────────────────────────────────────────────────────
-- `sejours_en_cours` = séjours ouverts à la fin de la journée considérée :
-- c'est la charge réelle du service, invisible dans un simple comptage
-- d'admissions.
--
-- Le calcul se fait par **balayage cumulé** du calendrier, et non en confrontant
-- chaque jour à chaque séjour. Un séjour pèse +1 à partir de son admission et
-- −1 à partir de sa sortie ; les séjours ouverts d'un jour sont donc la somme
-- des entrées moins la somme des sorties jusqu'à ce jour. C'est strictement
-- équivalent au comptage `admission <= jour AND (sortie IS NULL OR sortie > jour)`,
-- mais le coût passe de O(jours × séjours) — quadratique avec l'historique — à
-- O(séjours) pour l'agrégation, puis O(jours × services) pour le cumul.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_activite_service
ENGINE = MergeTree
ORDER BY (jour, service_code)
COMMENT 'Activité quotidienne par service : entrées, sorties, décès, séjours ouverts'
AS
WITH
-- Les mouvements, comptés une seule fois par (service, jour).
evenements AS
(
    SELECT service_code, admission_date AS jour,
           count() AS admissions, 0 AS sorties, 0 AS deces
    FROM eds_silver.fact_sejour
    GROUP BY service_code, jour

    UNION ALL

    SELECT service_code, assumeNotNull(discharge_date) AS jour,
           0 AS admissions, count() AS sorties, countIf(is_deces) AS deces
    FROM eds_silver.fact_sejour
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
-- Le cumul exige une ligne par jour même sans mouvement : un service peut
-- n'avoir ni entrée ni sortie tout en gardant des patients hospitalisés.
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
    q.jour            AS jour,
    q.service_code    AS service_code,
    d.service_label   AS service_label,
    q.admissions      AS admissions,
    q.sorties         AS sorties,
    q.deces           AS deces,
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
INNER JOIN eds_silver.dim_service AS d ON d.service_code = q.service_code
-- Le filtre se fait ici et non en HAVING : `sejours_en_cours` est une fonction
-- de fenêtrage, elle n'existe pas encore au moment de l'agrégation.
WHERE q.admissions + q.sorties + q.sejours_en_cours > 0;

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
