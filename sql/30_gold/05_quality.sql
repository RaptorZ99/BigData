-- Rapport qualité de la couche gold : ce que la diffusion a coûté en
-- suppression de cellules. C'est la preuve chiffrée que le k-anonymat n'est pas
-- qu'une intention affichée.
INSERT INTO ops.quality_report
    (run_id, layer, table_name, rule, rule_label, rows_in, rows_kept, rows_rejected, details)

SELECT
    '{run_id}', 'gold', 'cohorte_demographie_region', 'RGPD_k_anonymat',
    'Cellules supprimées car regroupant moins de 5 patients (seuil k = 5)',
    cellules_calculees,
    cellules_diffusees,
    cellules_supprimees,
    'Grain fin : pathologie × sexe × tranche d''âge × département'
FROM eds_gold_recherche.k_anonymat_controle

UNION ALL

SELECT
    '{run_id}', 'gold', 'cohorte_pathologie', 'RGPD_cohortes_diffusees',
    'Cohortes par pathologie effectivement diffusées (k >= 5)',
    (SELECT uniqExact(code_cim10) FROM eds_silver.fact_diagnostic),
    (SELECT count() FROM eds_gold_recherche.cohorte_pathologie),
    (SELECT uniqExact(code_cim10) FROM eds_silver.fact_diagnostic)
        - (SELECT count() FROM eds_gold_recherche.cohorte_pathologie),
    'Une pathologie dont la cohorte compte moins de 5 patients n''est pas diffusée'

UNION ALL

SELECT
    '{run_id}', 'gold', 'eds_gold_recherche', 'RGPD_minimisation',
    'Contrôle actif : aucune donnée identifiante dans la base recherche',
    (SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche'),
    (SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche'),
    (SELECT countIf(name IN ('nir', 'nom', 'prenom', 'birth_date', 'patient_id', 'patient_pseudo'))
     FROM system.columns WHERE database = 'eds_gold_recherche'),
    'Aucune colonne identifiante ni pseudonyme individuel ne doit être exposée';
