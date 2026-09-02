{{ config(order_by='tuple()') }}
-- KPI 2 — Taux de réadmission à 30 jours, indicateur de qualité des soins.
--
-- Grain : l'établissement. C'est un chiffre unique, celui que la direction suit ; sa
-- ventilation par service vit dans `kpi_readmissions_service`, et les deux se
-- réconcilient par construction (test `assert_readmissions_reconciliees`).
--
-- ⚠ Limite connue — la fenêtre d'observation. Une réadmission ne peut être constatée
-- que si l'entrepôt couvre la période où elle surviendrait. Les admissions s'arrêtant
-- au dernier jour déposé, les sorties tardives ont une probabilité structurellement
-- nulle d'être suivies d'une réadmission observable. Le taux publié est donc une
-- **borne basse** ; c'est documenté au rapport et rappelé sur le tableau de bord.
SELECT
    countIf(est_readmis)                              AS nb_readmissions_30j,
    count()                                           AS nb_sejours,
    round(100.0 * countIf(est_readmis) / count(), 2)  AS taux_readmission_30j_pct
FROM {{ ref('readmission_sejour') }}
