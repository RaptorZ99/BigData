-- Rapport qualité de la couche silver : combien de lignes lues, conservées,
-- écartées, règle par règle. C'est ce qui permet de justifier chaque chiffre
-- affiché dans les dashboards — et de prouver qu'aucune ligne ne disparaît
-- sans motif.
--
-- Convention : `rows_rejected` compte les lignes qui n'atteignent pas la table
-- cible (rejet ou absorption par déduplication) ; une règle purement
-- informative (flag, cas légitime) laisse `rows_rejected` à 0.

INSERT INTO ops.quality_report
    (run_id, layer, table_name, rule, rule_label, rows_in, rows_kept, rows_rejected, details)

-- Q1 — Le CHU redépose chaque jour tous ses patients : on ne garde que la
-- version la plus récente de chacun.
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q1_dedup_patients',
    'Déduplication des patients redéposés (dernière version conservée)',
    (SELECT count() FROM eds_bronze.patients),
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT count() FROM eds_bronze.patients) - (SELECT count() FROM eds_silver.dim_patient),
    'Fichiers cumulatifs : un même patient revient à chaque dépôt'

UNION ALL
-- Q2 — Incohérence temporelle : sortie antérieure à l'admission.
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q2_coherence_temporelle',
    'Séjours écartés : date de sortie antérieure à l''admission',
    (SELECT uniqExact(stay_id) FROM eds_bronze.sejours),
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT count() FROM eds_silver.sejours_rejets),
    'Lignes conservées et consultables dans eds_silver.sejours_rejets'

UNION ALL
-- Q3 — Un séjour sans date de sortie n'est pas une anomalie.
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q3_sejours_en_cours',
    'Séjours en cours conservés (sortie non renseignée = patient hospitalisé)',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT countIf(is_ongoing) FROM eds_silver.fact_sejour),
    0,
    'Cas métier légitime : exclu du calcul de la DMS, jamais rejeté'

UNION ALL
-- Q5 — Mode de sortie absent alors que la sortie est datée.
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q5_mode_sortie_absent',
    'Séjours conservés avec mode de sortie non renseigné (NULL)',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT countIf(discharge_mode IS NULL) FROM eds_silver.fact_sejour),
    0,
    'Information manquante à la source : conservée en NULL, pas inventée'

UNION ALL
-- Q7 — Admission postérieure à un décès déjà enregistré.
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q7_admission_post_deces',
    'Séjours signalés : admission postérieure à un décès du même patient',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT countIf(is_post_mortem_anomaly) FROM eds_silver.fact_sejour),
    0,
    'Incohérence de la source : signalée, non rejetée (le séjour reste cohérent en soi)'

UNION ALL
-- Q4 — Constantes hors plage physiologique (panne de capteur).
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'Q4_plages_physiologiques',
    'Relevés écartés : FC hors 20-250 bpm, SpO2 hors 50-100 %, température hors 30-45 °C',
    (SELECT count() FROM eds_bronze.monitoring),
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT countIf(reject_reason LIKE '%out_of_range%') FROM eds_silver.monitoring_rejets),
    'Motif détaillé par borne dans eds_silver.monitoring_rejets'

UNION ALL
-- Cascade — un relevé dont le séjour parent est écarté ne peut pas être rattaché.
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'C1_cascade_monitoring',
    'Relevés écartés en cascade : séjour parent invalide ou inconnu',
    (SELECT count() FROM eds_bronze.monitoring),
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT countIf(reject_reason LIKE '%parent_stay_rejected%') FROM eds_silver.monitoring_rejets),
    'Nécessaire à la propagation de service_code depuis le séjour'

UNION ALL
-- Cascade — idem pour les diagnostics.
SELECT
    '{run_id}', 'silver', 'fact_diagnostic', 'C2_cascade_diagnostics',
    'Diagnostics écartés en cascade : séjour parent invalide ou inconnu',
    (SELECT count() FROM eds_bronze.diagnostics),
    (SELECT count() FROM eds_silver.fact_diagnostic),
    (SELECT count() FROM eds_bronze.diagnostics) - (SELECT count() FROM eds_silver.fact_diagnostic),
    'Inclut la déduplication éventuelle sur (séjour, code, type)'

UNION ALL
-- Q8 — Relevé postérieur à la sortie : contrôle actif, attendu à 0.
SELECT
    '{run_id}', 'silver', 'fact_monitoring', 'Q8_releve_post_sortie',
    'Contrôle actif : relevés postérieurs à la sortie du patient',
    (SELECT count() FROM eds_silver.fact_monitoring),
    (SELECT countIf(is_after_discharge) FROM eds_silver.fact_monitoring),
    0,
    'Attendu à 0 : ces relevés appartenaient aux séjours temporellement incohérents'

UNION ALL
-- Q6 — Contrôles de format et d'intégrité référentielle. Attendus à 0, mais
-- exécutés à chaque run : c'est leur passage au vert qui a de la valeur.
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q6_sexe_normalise',
    'Contrôle actif : sexe hors valeurs attendues (M/F)',
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT countIf(sex IN ('M', 'F')) FROM eds_silver.dim_patient),
    (SELECT countIf(sex NOT IN ('M', 'F')) FROM eds_silver.dim_patient),
    'Normalisation appliquée dès la collecte'

UNION ALL
SELECT
    '{run_id}', 'silver', 'dim_patient', 'Q6_annee_naissance',
    'Contrôle actif : année de naissance hors plage plausible (1900 → année courante)',
    (SELECT count() FROM eds_silver.dim_patient),
    (SELECT countIf(birth_year BETWEEN 1900 AND toYear(today())) FROM eds_silver.dim_patient),
    (SELECT countIf(birth_year NOT BETWEEN 1900 AND toYear(today())) FROM eds_silver.dim_patient),
    'Date de naissance généralisée à l''année dès l''entrée du lake'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q6_service_referentiel',
    'Contrôle actif : code service absent du référentiel',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT countIf(service_code IN (SELECT service_code FROM eds_silver.dim_service))
     FROM eds_silver.fact_sejour),
    (SELECT countIf(service_code NOT IN (SELECT service_code FROM eds_silver.dim_service))
     FROM eds_silver.fact_sejour),
    'Intégrité référentielle fact_sejour → dim_service'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_diagnostic', 'Q6_cim10_referentiel',
    'Contrôle actif : code CIM-10 absent du référentiel',
    (SELECT count() FROM eds_silver.fact_diagnostic),
    (SELECT countIf(code_cim10 IN (SELECT code_cim10 FROM eds_silver.dim_cim10))
     FROM eds_silver.fact_diagnostic),
    (SELECT countIf(code_cim10 NOT IN (SELECT code_cim10 FROM eds_silver.dim_cim10))
     FROM eds_silver.fact_diagnostic),
    'Intégrité référentielle fact_diagnostic → dim_cim10'

UNION ALL
SELECT
    '{run_id}', 'silver', 'fact_sejour', 'Q6_patient_referentiel',
    'Contrôle actif : séjour rattaché à un patient inconnu',
    (SELECT count() FROM eds_silver.fact_sejour),
    (SELECT countIf(patient_pseudo IN (SELECT patient_pseudo FROM eds_silver.dim_patient))
     FROM eds_silver.fact_sejour),
    (SELECT countIf(patient_pseudo NOT IN (SELECT patient_pseudo FROM eds_silver.dim_patient))
     FROM eds_silver.fact_sejour),
    'Intégrité référentielle fact_sejour → dim_patient';
