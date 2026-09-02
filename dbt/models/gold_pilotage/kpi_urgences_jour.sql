{{ config(order_by='admission_date') }}
-- KPI 3 — Activité quotidienne des urgences.
--
-- Grain : le jour d'admission. « Passage aux urgences » = séjour dont l'unité
-- d'hospitalisation est URGENCES. L'autre lecture possible — les admissions en mode
-- « urgence » tous services confondus — répond à une question différente (le mode
-- d'entrée, pas le service) et vit dans `kpi_flux`.
--
-- `nb_encore_presents` isole les séjours sans date de sortie : ils sont comptés dans
-- les passages mais exclus de la durée moyenne, qui serait sinon calculée sur une
-- hospitalisation inachevée.
SELECT
    admission_date                              AS admission_date,
    count()                                     AS nb_passages,
    countIf(is_ongoing)                         AS nb_encore_presents,
    round(avg(duree_heures), 1)                 AS duree_moy_heures
FROM {{ ref('fact_sejour') }}
WHERE is_service_urgences
GROUP BY admission_date
