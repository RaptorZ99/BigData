-- Rapport qualité de la couche gold : ce que la diffusion a coûté en
-- suppression de cellules. C'est la preuve chiffrée que le k-anonymat n'est pas
-- qu'une intention affichée.
INSERT INTO ops.quality_report
    (run_id, layer, table_name, rule, rule_label,
     rows_in, rows_kept, rows_rejected, rows_flagged, details)

-- Deux lignes distinctes : le seuil au grain fin, et la suppression
-- complémentaire sur les marges. Les confondre sous un même libellé donnerait
-- l'impression d'un doublon.
SELECT
    '{run_id}', 'gold', table_cible,
    if(table_cible = 'cohorte_demographie_region',
       'RGPD_k_anonymat',
       'RGPD_suppression_complementaire'),
    concat('Cellules non diffusées — ', motif),
    cellules_calculees,
    cellules_diffusees,
    cellules_supprimees,
    0,
    if(table_cible = 'cohorte_demographie_region',
       'Grain fin : pathologie × sexe × tranche d''âge × département',
       'Marge retirée dès qu''une de ses cellules fines l''est : sinon la valeur cachée se retrouverait par soustraction')
FROM eds_gold_recherche.k_anonymat_controle

UNION ALL

SELECT
    '{run_id}', 'gold', 'cohorte_pathologie', 'RGPD_cohortes_diffusees',
    'Cohortes par pathologie effectivement diffusées (k >= 5)',
    (SELECT uniqExact(code_cim10) FROM eds_silver.fact_diagnostic),
    (SELECT count() FROM eds_gold_recherche.cohorte_pathologie),
    (SELECT uniqExact(code_cim10) FROM eds_silver.fact_diagnostic)
        - (SELECT count() FROM eds_gold_recherche.cohorte_pathologie),
    0,
    'Une pathologie dont la cohorte compte moins de 5 patients n''est pas diffusée'

UNION ALL

SELECT
    '{run_id}', 'gold', 'eds_gold_recherche', 'RGPD_minimisation',
    'Contrôle : aucune colonne identifiante exposée à la recherche',
    (SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche'),
    (SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche'),
    0,
    (SELECT countIf(name IN ('nir', 'nom', 'prenom', 'birth_date', 'patient_id', 'patient_pseudo'))
     FROM system.columns WHERE database = 'eds_gold_recherche'),
    'Ni identifiant direct, ni pseudonyme individuel : seuls des agrégats sont diffusés';
