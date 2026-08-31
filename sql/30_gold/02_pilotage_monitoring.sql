-- Gold pilotage — surveillance des constantes, bâtie sur l'étoile fact_monitoring.
-- `service_code` étant porté par le fait lui-même, aucune jointure vers
-- fact_sejour n'est nécessaire : une seule étoile suffit à répondre.

CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_alertes_monitoring
ENGINE = MergeTree
ORDER BY (releve_date, service_code)
COMMENT 'Relevés de constantes en alerte, par jour et par service (REA et CARDIO)'
AS
SELECT
    m.releve_date                                       AS releve_date,
    m.service_code                                      AS service_code,
    d.service_label                                     AS service_label,
    count()                                             AS nb_releves,
    countIf(m.is_alert)                                 AS nb_alertes,
    countIf(m.alert_hr)                                 AS nb_alertes_frequence_cardiaque,
    countIf(m.alert_spo2)                               AS nb_alertes_saturation,
    countIf(m.alert_temp)                               AS nb_alertes_temperature,
    round(100.0 * countIf(m.is_alert) / count(), 1)     AS pct_alertes,
    uniqExact(m.stay_id)                                AS nb_sejours_monitores
FROM eds_silver.fact_monitoring AS m
INNER JOIN eds_silver.dim_service AS d USING (service_code)
GROUP BY releve_date, service_code, service_label;

-- Vue synthétique pour les tuiles de tête du dashboard.
CREATE OR REPLACE TABLE eds_gold_pilotage.kpi_synthese
ENGINE = MergeTree
ORDER BY tuple()
COMMENT 'Chiffres clés de l''activité, pour les tuiles de synthèse du dashboard'
AS
SELECT
    (SELECT count() FROM eds_silver.fact_sejour)                            AS nb_sejours,
    (SELECT uniqExact(patient_pseudo) FROM eds_silver.fact_sejour)          AS nb_patients,
    (SELECT countIf(is_ongoing) FROM eds_silver.fact_sejour)                AS nb_sejours_en_cours,
    (SELECT round(avg(duree_jours), 2) FROM eds_silver.fact_sejour
     WHERE discharge_ts IS NOT NULL)                                        AS dms_globale_jours,
    -- Réadmissions : restreintes aux sorties dont la fenêtre d'observation
    -- n'est pas vide. Les sorties postérieures à la dernière admission connue
    -- ne peuvent rien constater ; les inclure diluerait le taux d'un facteur 8
    -- sur ce jeu de données (cf. commentaire de kpi_readmissions_30j).
    (SELECT sum(readmissions_30j) FROM eds_gold_pilotage.kpi_readmissions_30j
     WHERE jours_observables > 0)                                           AS nb_readmissions_30j,
    (SELECT sum(sorties_eligibles) FROM eds_gold_pilotage.kpi_readmissions_30j
     WHERE jours_observables > 0)                                           AS nb_sorties_observables,
    (SELECT round(100.0 * sum(readmissions_30j) / sum(sorties_eligibles), 1)
     FROM eds_gold_pilotage.kpi_readmissions_30j
     WHERE jours_observables > 0)                                           AS taux_readmission_pct,
    -- Part des sorties sur lesquelles l'indicateur peut se prononcer.
    (SELECT round(100.0 * sumIf(sorties_eligibles, jours_observables > 0)
                  / sum(sorties_eligibles), 1)
     FROM eds_gold_pilotage.kpi_readmissions_30j)                           AS pct_sorties_observables,
    (SELECT count() FROM eds_silver.fact_monitoring)                        AS nb_releves,
    (SELECT countIf(is_alert) FROM eds_silver.fact_monitoring)              AS nb_releves_alerte,
    (SELECT round(100.0 * countIf(is_alert) / count(), 1)
     FROM eds_silver.fact_monitoring)                                       AS pct_releves_alerte;
