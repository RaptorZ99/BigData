{{ config(
    materialized='incremental',
    incremental_strategy='append',
    order_by='(run_id, layer, table_name, rule)',
    ttl='checked_at + INTERVAL 1 YEAR'
) }}
-- Rapport qualité : combien de lignes lues, conservées, écartées, signalées — règle par
-- règle. C'est ce qui permet de justifier chaque chiffre affiché dans les tableaux de
-- bord, et de prouver qu'aucune ligne ne disparaît sans motif.
--
-- Trois natures de règles cohabitent, d'où quatre compteurs :
--   * REJET        — la ligne quitte l'entrepôt et part dans une table de rejets
--                    (`rows_rejected`) ;
--   * SIGNALEMENT  — la ligne est conservée mais marquée (`rows_flagged`) ;
--   * CONTRÔLE     — vérification attendue à zéro, dont le passage au vert est en soi
--                    l'information.
--
-- Pourquoi un modèle dbt, et pourquoi `incremental` :
--   * modèle → le graphe garantit qu'il s'exécute APRÈS tout ce qu'il compte. Dans la
--     version SQL, cet ordre reposait sur le préfixe numérique des fichiers et sur une
--     règle écrite à la main (« 05 en dernier »). Elle disparaît.
--   * append → une exécution ajoute ses 18 lignes sans effacer l'historique. Un `table`
--     écraserait le rapport du run précédent.
--
-- ⚠ `eds run --full-refresh` ne doit JAMAIS passer `--full-refresh` à dbt : le premier
-- signifie « ré-ingérer tous les jours », le second détruirait cet historique.
--
-- Tous les compteurs sont castés en Int64. Un `UNION ALL` réconciliant `count()`
-- (UInt64) et une soustraction (Int64) produirait un `Variant`, type sur lequel un
-- simple `sum()` échoue — et cette table est recopiée dans la base de pilotage.
--
-- Deux règles gold lisent `system.columns` ou agrègent des tables sans les référencer
-- par une colonne : le graphe ne peut pas le deviner, on l'y force.
-- depends_on: {{ ref('cohorte_demographie_region') }}
-- depends_on: {{ ref('cohorte_demographie_globale') }}
-- depends_on: {{ ref('prevalence_pathologie') }}

{% set run_id = var('run_id') %}

-- ── Q1 · REJET (déduplication) ──────────────────────────────────────────────
-- Le CHU redépose chaque jour tous ses patients : on ne garde que la version la plus
-- récente de chacun.
SELECT
    '{{ run_id }}' AS run_id, 'silver' AS layer, 'dim_patient' AS table_name,
    'Q1_dedup_patients' AS rule,
    'Déduplication des patients redéposés (dernière version conservée)' AS rule_label,
    toInt64((SELECT count() FROM {{ source('bronze', 'patients') }}))    AS rows_in,
    toInt64((SELECT count() FROM {{ ref('dim_patient') }}))              AS rows_kept,
    toInt64((SELECT count() FROM {{ source('bronze', 'patients') }})
          - (SELECT count() FROM {{ ref('dim_patient') }}))              AS rows_rejected,
    toInt64(0)                                                           AS rows_flagged,
    'Fichiers cumulatifs : un même patient revient à chaque dépôt'       AS details,
    now()                                                                AS checked_at

UNION ALL
-- ── Q2 · REJET ──────────────────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q2_coherence_temporelle',
    'Séjours écartés : date de sortie antérieure à l''admission',
    toInt64((SELECT uniqExact(stay_id) FROM {{ source('bronze', 'sejours') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('sejours_rejets') }})),
    toInt64(0),
    'Lignes conservées et consultables dans eds_silver.sejours_rejets',
    now()

UNION ALL
-- ── Q4 · REJET ──────────────────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_monitoring', 'Q4_plages_physiologiques',
    'Relevés écartés : FC hors 20-250 bpm, SpO2 hors 50-100 %, température hors 30-45 °C',
    -- Lues au grain du fait (séjour, horodatage), qui est aussi celui de la
    -- déduplication : sinon un relevé redéposé gonflerait le dénominateur.
    toInt64((SELECT uniqExact((stay_id, ts)) FROM {{ source('bronze', 'monitoring') }})),
    toInt64((SELECT count() FROM {{ ref('fact_monitoring') }})),
    toInt64((SELECT countIf(reject_reason LIKE '%out_of_range%')
             FROM {{ ref('monitoring_rejets') }})),
    toInt64(0),
    'Signature d''une panne de capteur ; motif détaillé par borne dans monitoring_rejets',
    now()

UNION ALL
-- ── C1 · REJET en cascade ───────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_monitoring', 'C1_cascade_monitoring',
    'Relevés écartés en cascade : séjour parent invalide ou inconnu',
    toInt64((SELECT uniqExact((stay_id, ts)) FROM {{ source('bronze', 'monitoring') }})),
    toInt64((SELECT count() FROM {{ ref('fact_monitoring') }})),
    toInt64((SELECT countIf(reject_reason LIKE '%parent_stay_rejected%')
             FROM {{ ref('monitoring_rejets') }})),
    toInt64(0),
    'Nécessaire à la propagation de service_code depuis le séjour',
    now()

UNION ALL
-- ── C2 · REJET en cascade ───────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_diagnostic', 'C2_cascade_diagnostics',
    'Diagnostics écartés en cascade : séjour parent invalide ou inconnu',
    toInt64((SELECT count() FROM {{ source('bronze', 'diagnostics') }})),
    toInt64((SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64((SELECT count() FROM {{ source('bronze', 'diagnostics') }})
          - (SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64(0),
    'Inclut la déduplication éventuelle sur (séjour, code, type)',
    now()

UNION ALL
-- ── Q3 · SIGNALEMENT (cas métier légitime) ──────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q3_sejours_en_cours',
    'Séjours en cours : sortie non renseignée = patient encore hospitalisé',
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64(0),
    toInt64((SELECT countIf(is_ongoing) FROM {{ ref('fact_sejour') }})),
    'Cas métier légitime : conservé, mais exclu du calcul de la DMS',
    now()

UNION ALL
-- ── Q5 · SIGNALEMENT ────────────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q5_mode_sortie_absent',
    'Séjours sortis dont le mode de sortie n''est pas renseigné',
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64(0),
    -- On restreint aux séjours effectivement terminés : un séjour en cours n'a pas
    -- encore de mode de sortie, et il est déjà compté par la règle Q3. Sans ce filtre,
    -- les 1 190 séjours ouverts seraient signalés deux fois.
    toInt64((SELECT countIf(discharge_ts IS NOT NULL AND discharge_mode IS NULL)
             FROM {{ ref('fact_sejour') }})),
    'Information manquante à la source : conservée en NULL, jamais inventée',
    now()

UNION ALL
-- ── Q7 · SIGNALEMENT ────────────────────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q7_admission_post_deces',
    'Séjours dont l''admission est postérieure à un décès du même patient',
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64(0),
    toInt64((SELECT countIf(is_post_mortem_anomaly) FROM {{ ref('fact_sejour') }})),
    'Incohérence de la source : signalée, non rejetée (le séjour reste cohérent en soi)',
    now()

UNION ALL
-- ── Q8 · CONTRÔLE (attendu à zéro) ──────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_monitoring', 'Q8_releve_post_sortie',
    'Contrôle : relevés postérieurs à la sortie du patient',
    toInt64((SELECT count() FROM {{ ref('fact_monitoring') }})),
    toInt64((SELECT count() FROM {{ ref('fact_monitoring') }})),
    toInt64(0),
    toInt64((SELECT countIf(is_after_discharge) FROM {{ ref('fact_monitoring') }})),
    'Attendu à 0 : ces relevés appartenaient aux séjours temporellement incohérents',
    now()

UNION ALL
-- ── Q6 · CONTRÔLES de format et d'intégrité référentielle ───────────────────
-- Attendus à zéro, mais exécutés à chaque run : c'est leur passage au vert qui a de
-- la valeur.
SELECT
    '{{ run_id }}', 'silver', 'dim_patient', 'Q6_sexe_normalise',
    'Contrôle : sexe hors valeurs attendues (M/F)',
    toInt64((SELECT count() FROM {{ ref('dim_patient') }})),
    toInt64((SELECT countIf(sex IN ('M', 'F')) FROM {{ ref('dim_patient') }})),
    toInt64(0),
    toInt64((SELECT countIf(sex NOT IN ('M', 'F')) FROM {{ ref('dim_patient') }})),
    'Normalisation appliquée dès la collecte',
    now()

UNION ALL
SELECT
    '{{ run_id }}', 'silver', 'dim_patient', 'Q6_annee_naissance',
    'Contrôle : année de naissance hors plage plausible (1900 → année courante)',
    toInt64((SELECT count() FROM {{ ref('dim_patient') }})),
    toInt64((SELECT countIf(birth_year BETWEEN 1900 AND toYear(today()))
             FROM {{ ref('dim_patient') }})),
    toInt64(0),
    toInt64((SELECT countIf(birth_year NOT BETWEEN 1900 AND toYear(today()))
             FROM {{ ref('dim_patient') }})),
    'Date de naissance généralisée à l''année dès l''entrée du lake',
    now()

UNION ALL
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q6_service_referentiel',
    'Contrôle : code service absent du référentiel',
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64(0),
    toInt64((SELECT countIf(service_code NOT IN
                (SELECT service_code FROM {{ ref('dim_service') }}))
             FROM {{ ref('fact_sejour') }})),
    'Intégrité référentielle fact_sejour → dim_service',
    now()

UNION ALL
SELECT
    '{{ run_id }}', 'silver', 'fact_sejour', 'Q6_patient_referentiel',
    'Contrôle : séjour rattaché à un patient inconnu',
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64((SELECT count() FROM {{ ref('fact_sejour') }})),
    toInt64(0),
    toInt64((SELECT countIf(patient_pseudo NOT IN
                (SELECT patient_pseudo FROM {{ ref('dim_patient') }}))
             FROM {{ ref('fact_sejour') }})),
    'Intégrité référentielle fact_sejour → dim_patient',
    now()

UNION ALL
SELECT
    '{{ run_id }}', 'silver', 'fact_diagnostic', 'Q6_cim10_referentiel',
    'Contrôle : code CIM-10 absent du référentiel',
    toInt64((SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64((SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64(0),
    toInt64((SELECT countIf(code_cim10 NOT IN
                (SELECT code_cim10 FROM {{ ref('dim_cim10') }}))
             FROM {{ ref('fact_diagnostic') }})),
    'Intégrité référentielle fact_diagnostic → dim_cim10',
    now()

UNION ALL
-- ═══ Couche gold : ce que la diffusion a coûté en suppression de cellules ═══
-- La preuve chiffrée que le k-anonymat n'est pas qu'une intention affichée.
-- Deux lignes distinctes : le seuil au grain fin, et la suppression complémentaire
-- sur les marges. Les confondre donnerait l'impression d'un doublon.
SELECT
    '{{ run_id }}', 'gold', table_cible,
    if(table_cible = 'cohorte_demographie_region',
       'RGPD_k_anonymat',
       'RGPD_suppression_complementaire'),
    concat('Cellules non diffusées — ', motif),
    toInt64(cellules_calculees),
    toInt64(cellules_diffusees),
    toInt64(cellules_supprimees),
    toInt64(0),
    if(table_cible = 'cohorte_demographie_region',
       'Grain fin : pathologie × sexe × tranche d''âge × département',
       'Marge retirée dès qu''une de ses cellules fines l''est : sinon la valeur cachée se retrouverait par soustraction'),
    now()
FROM {{ ref('k_anonymat_controle') }}

UNION ALL
SELECT
    '{{ run_id }}', 'gold', 'cohorte_pathologie', 'RGPD_cohortes_diffusees',
    'Cohortes par pathologie effectivement diffusées (k >= {{ var("seuil_k") }})',
    toInt64((SELECT uniqExact(code_cim10) FROM {{ ref('fact_diagnostic') }})),
    toInt64((SELECT count() FROM {{ ref('cohorte_pathologie') }})),
    toInt64((SELECT uniqExact(code_cim10) FROM {{ ref('fact_diagnostic') }})
          - (SELECT count() FROM {{ ref('cohorte_pathologie') }})),
    toInt64(0),
    'Une pathologie dont la cohorte compte moins de {{ var("seuil_k") }} patients n''est pas diffusée',
    now()

UNION ALL
SELECT
    '{{ run_id }}', 'gold', 'eds_gold_recherche', 'RGPD_minimisation',
    'Contrôle : aucune colonne identifiante exposée à la recherche',
    toInt64((SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche')),
    toInt64((SELECT count() FROM system.columns WHERE database = 'eds_gold_recherche')),
    toInt64(0),
    toInt64((SELECT countIf(name IN
                ('nir', 'nom', 'prenom', 'birth_date', 'patient_id', 'patient_pseudo'))
             FROM system.columns WHERE database = 'eds_gold_recherche')),
    'Ni identifiant direct, ni pseudonyme individuel : seuls des agrégats sont diffusés',
    now()
