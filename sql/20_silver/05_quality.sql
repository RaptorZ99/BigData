-- Rapport qualité de la couche silver : combien de lignes lues, conservées,
-- écartées, signalées — règle par règle. C'est ce qui permet de justifier chaque
-- chiffre affiché dans les dashboards, et de prouver qu'aucune ligne ne
-- disparaît sans motif.
--
-- Trois natures de règles cohabitent, d'où quatre compteurs :
--   * REJET        — la ligne quitte l'entrepôt et part dans une table de rejets
--                    (`rows_rejected`) ;
--   * SIGNALEMENT  — la ligne est conservée mais marquée (`rows_flagged`) ;
--   * CONTRÔLE     — vérification attendue à zéro, dont le passage au vert est
--                    en soi l'information.

INSERT INTO ops.quality_report
    (run_id, layer, table_name, rule, rule_label,
     rows_in, rows_kept, rows_rejected, rows_flagged, details)

-- ── Q1 · REJET (déduplication) ──────────────────────────────────────────────
-- Le CHU redépose chaque jour tous ses patients : on ne garde que la version la
-- plus récente de chacun.
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q1_dedup_patients',
    'Déduplication des patients redéposés (dernière version conservée)',
    (SELECT count() FROM eds_bronze.patients),
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT count() FROM eds_bronze.patients) - (SELECT count() FROM eds_silver.dim_patient),
    0,
    'Fichiers cumulatifs : un même patient revient à chaque dépôt'

UNION ALL
-- ── Q2 · REJET ──────────────────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q2_coherence_temporelle',
    'Séjours écartés : date de sortie antérieure à l''admission',
    (SELECT uniqExact(stay_id) FROM eds_bronze.sejours),
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.sejours_rejets),
    0,
    'Lignes conservées et consultables dans eds_silver.sejours_rejets'

UNION ALL
-- ── Q4 · REJET ──────────────────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'Q4_plages_physiologiques',
    'Relevés écartés : FC hors 20-250 bpm, SpO2 hors 50-100 %, température hors 30-45 °C',
    (SELECT count() FROM eds_bronze.monitoring),
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT countIf(reject_reason LIKE '%out_of_range%') FROM eds_silver.monitoring_rejets),
    0,
    'Signature d''une panne de capteur ; motif détaillé par borne dans monitoring_rejets'

UNION ALL
-- ── C1 · REJET en cascade ───────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'C1_cascade_monitoring',
    'Relevés écartés en cascade : séjour parent invalide ou inconnu',
    (SELECT count() FROM eds_bronze.monitoring),
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT countIf(reject_reason LIKE '%parent_stay_rejected%') FROM eds_silver.monitoring_rejets),
    0,
    'Nécessaire à la propagation de service_code depuis le séjour'

UNION ALL
-- ── C2 · REJET en cascade ───────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_diagnostic', 'C2_cascade_diagnostics',
    'Diagnostics écartés en cascade : séjour parent invalide ou inconnu',
    (SELECT count() FROM eds_bronze.diagnostics),
    (SELECT count() FROM eds_silver.fact_diagnostic),
    (SELECT count() FROM eds_bronze.diagnostics) - (SELECT count() FROM eds_silver.fact_diagnostic),
    0,
    'Inclut la déduplication éventuelle sur (séjour, code, type)'

UNION ALL
-- ── Q3 · SIGNALEMENT (cas métier légitime) ──────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q3_sejours_en_cours',
    'Séjours en cours : sortie non renseignée = patient encore hospitalisé',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.fact_sejour),
    0,
    (SELECT countIf(is_ongoing) FROM eds_silver.fact_sejour),
    'Cas métier légitime : conservé, mais exclu du calcul de la DMS'

UNION ALL
-- ── Q5 · SIGNALEMENT ────────────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q5_mode_sortie_absent',
    'Séjours dont le mode de sortie n''est pas renseigné',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.fact_sejour),
    0,
    (SELECT countIf(discharge_mode IS NULL) FROM eds_silver.fact_sejour),
    'Information manquante à la source : conservée en NULL, jamais inventée'

UNION ALL
-- ── Q7 · SIGNALEMENT ────────────────────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q7_admission_post_deces',
    'Séjours dont l''admission est postérieure à un décès du même patient',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.fact_sejour),
    0,
    (SELECT countIf(is_post_mortem_anomaly) FROM eds_silver.fact_sejour),
    'Incohérence de la source : signalée, non rejetée (le séjour reste cohérent en soi)'

UNION ALL
-- ── Q8 · CONTRÔLE (attendu à zéro) ──────────────────────────────────────────
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'Q8_releve_post_sortie',
    'Contrôle : relevés postérieurs à la sortie du patient',
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT count() FROM eds_silver.fact_monitoring),
    0,
    (SELECT countIf(is_after_discharge) FROM eds_silver.fact_monitoring),
    'Attendu à 0 : ces relevés appartenaient aux séjours temporellement incohérents'

UNION ALL
-- ── Q6 · CONTRÔLES de format et d'intégrité référentielle ───────────────────
-- Attendus à zéro, mais exécutés à chaque run : c'est leur passage au vert qui
-- a de la valeur.
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q6_sexe_normalise',
    'Contrôle : sexe hors valeurs attendues (M/F)',
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT countIf(sex IN ('M', 'F')) FROM eds_silver.dim_patient),
    0,
    (SELECT countIf(sex NOT IN ('M', 'F')) FROM eds_silver.dim_patient),
    'Normalisation appliquée dès la collecte'

UNION ALL
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q6_annee_naissance',
    'Contrôle : année de naissance hors plage plausible (1900 → année courante)',
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT countIf(birth_year BETWEEN 1900 AND toYear(today())) FROM eds_silver.dim_patient),
    0,
    (SELECT countIf(birth_year NOT BETWEEN 1900 AND toYear(today())) FROM eds_silver.dim_patient),
    'Date de naissance généralisée à l''année dès l''entrée du lake'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q6_service_referentiel',
    'Contrôle : code service absent du référentiel',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.fact_sejour),
    0,
    (SELECT countIf(service_code NOT IN (SELECT service_code FROM eds_silver.dim_service))
     FROM eds_silver.fact_sejour),
    'Intégrité référentielle fact_sejour → dim_service'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q6_patient_referentiel',
    'Contrôle : séjour rattaché à un patient inconnu',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.fact_sejour),
    0,
    (SELECT countIf(patient_pseudo NOT IN (SELECT patient_pseudo FROM eds_silver.dim_patient))
     FROM eds_silver.fact_sejour),
    'Intégrité référentielle fact_sejour → dim_patient'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_diagnostic', 'Q6_cim10_referentiel',
    'Contrôle : code CIM-10 absent du référentiel',
    (SELECT count() FROM eds_silver.fact_diagnostic),
    (SELECT count() FROM eds_silver.fact_diagnostic),
    0,
    (SELECT countIf(code_cim10 NOT IN (SELECT code_cim10 FROM eds_silver.dim_cim10))
     FROM eds_silver.fact_diagnostic),
    'Intégrité référentielle fact_diagnostic → dim_cim10';
