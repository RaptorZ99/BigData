{{ config(order_by='tuple()') }}
-- Chiffres clés de l'activité, pour les tuiles de synthèse du tableau de bord.
--
-- `ifNotFinite(…, 0)` protège les moyennes et les taux : sur un entrepôt vide — juste
-- après un `make reset`, ou pendant un premier chargement — une division 0/0 afficherait
-- « nan » dans une tuile de direction. Un zéro explicite est lisible ; « nan » ne l'est pas.
SELECT
    (SELECT count() FROM {{ ref('fact_sejour') }})                          AS nb_sejours,
    (SELECT uniqExact(patient_pseudo) FROM {{ ref('fact_sejour') }})        AS nb_patients,
    (SELECT countIf(is_ongoing) FROM {{ ref('fact_sejour') }})              AS nb_sejours_en_cours,
    (SELECT ifNotFinite(round(avg(duree_jours), 2), 0) FROM {{ ref('fact_sejour') }}
     WHERE discharge_ts IS NOT NULL)                                        AS dms_globale_jours,
    -- Réadmissions : restreintes aux sorties dont la fenêtre d'observation n'est pas
    -- vide. Les sorties postérieures à la dernière admission connue ne peuvent rien
    -- constater ; les inclure diluerait le taux, d'autant plus que la période est courte.
    (SELECT sum(readmissions_30j) FROM {{ ref('kpi_readmissions_30j') }}
     WHERE jours_observables > 0)                                           AS nb_readmissions_30j,
    (SELECT sum(sorties_eligibles) FROM {{ ref('kpi_readmissions_30j') }}
     WHERE jours_observables > 0)                                           AS nb_sorties_observables,
    (SELECT ifNotFinite(round(100.0 * sum(readmissions_30j) / sum(sorties_eligibles), 1), 0)
     FROM {{ ref('kpi_readmissions_30j') }}
     WHERE jours_observables > 0)                                           AS taux_readmission_pct,
    -- Part des sorties sur lesquelles l'indicateur peut se prononcer.
    (SELECT ifNotFinite(round(100.0 * sumIf(sorties_eligibles, jours_observables > 0)
                              / sum(sorties_eligibles), 1), 0)
     FROM {{ ref('kpi_readmissions_30j') }})                                AS pct_sorties_observables,
    (SELECT count() FROM {{ ref('fact_monitoring') }})                      AS nb_releves,
    (SELECT countIf(is_alert) FROM {{ ref('fact_monitoring') }})            AS nb_releves_alerte,
    (SELECT ifNotFinite(round(100.0 * countIf(is_alert) / count(), 1), 0)
     FROM {{ ref('fact_monitoring') }})                                     AS pct_releves_alerte,
    -- Horodatage de construction de la couche gold. Comparé à celui de silver, il rend
    -- détectable un échec survenu APRÈS la construction de silver : sans lui, le run
    -- suivant conclurait « tout est à jour » et les tableaux de bord figeraient les
    -- chiffres de l'avant-dernier traitement.
    now()                                                                   AS _built_at
