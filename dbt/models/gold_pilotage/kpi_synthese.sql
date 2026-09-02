{{ config(order_by='tuple()') }}
-- Chiffres clés de l'activité, pour les tuiles de synthèse du tableau de bord.
--
-- Chaque valeur est reprise telle quelle d'une table gold — jamais recalculée ici.
-- Une tuile et le graphique qui la détaille affichent donc nécessairement le même
-- chiffre.
--
-- `ifNotFinite(…, 0)` protège les moyennes : sur un entrepôt vide — juste après un
-- `make reset`, ou pendant un premier chargement — une division 0/0 afficherait
-- « nan » dans une tuile de direction. Un zéro explicite est lisible ; « nan » ne l'est pas.
SELECT
    (SELECT count() FROM {{ ref('fact_sejour') }})                          AS nb_sejours,
    (SELECT uniqExact(patient_pseudo) FROM {{ ref('fact_sejour') }})        AS nb_patients,
    (SELECT countIf(is_ongoing) FROM {{ ref('fact_sejour') }})              AS nb_sejours_en_cours,
    (SELECT ifNotFinite(round(avg(duree_jours), 2), 0) FROM {{ ref('fact_sejour') }}
     WHERE discharge_ts IS NOT NULL)                                        AS dms_globale_jours,

    (SELECT nb_readmissions_30j FROM {{ ref('kpi_readmissions_30j') }})     AS nb_readmissions_30j,
    (SELECT taux_readmission_30j_pct FROM {{ ref('kpi_readmissions_30j') }}) AS taux_readmission_pct,

    (SELECT sum(nb_releves) FROM {{ ref('kpi_alertes_jour') }})             AS nb_releves,
    (SELECT sum(nb_alertes) FROM {{ ref('kpi_alertes_jour') }})             AS nb_releves_alerte,
    (SELECT ifNotFinite(round(100.0 * sum(nb_alertes) / sum(nb_releves), 1), 0)
     FROM {{ ref('kpi_alertes_jour') }})                                    AS pct_releves_alerte,

    -- Évolution du 29 août 2026 : actes médicaux et facturation T2A.
    (SELECT sum(nb_actes) FROM {{ ref('kpi_actes_service') }})              AS nb_actes,
    (SELECT sum(montant_facture_euros) FROM {{ ref('kpi_actes_service') }}) AS montant_facture_euros,

    -- Horodatage de construction de la couche gold. Comparé à celui de silver, il rend
    -- détectable un échec survenu APRÈS la construction de silver : sans lui, le run
    -- suivant conclurait « tout est à jour » et les tableaux de bord figeraient les
    -- chiffres de l'avant-dernier traitement.
    now()                                                                   AS _built_at
