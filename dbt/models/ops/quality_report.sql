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
-- Un rejet ne vaut que pour la table où vit l'anomalie : un séjour aux horodatages
-- incohérents est écarté de `fact_sejour`, mais ses diagnostics et ses relevés restent
-- dans l'entrepôt. Voir l'encadré de `stg_sejours`. C'est pourquoi aucune règle
-- « cascade » n'apparaît plus ici : il n'y en a plus.
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
-- La règle de minimisation lit `system.columns` sans référencer aucun modèle : le
-- graphe ne peut pas deviner qu'elle doit attendre la couche recherche, on l'y force.
-- depends_on: {{ ref('cohorte_demographie') }}
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
    'Seuls les horodatages sont invalides : diagnostics et relevés du séjour restent dans l''entrepôt',
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
-- ── C1 · CONTRÔLE (attendu à zéro) ──────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_monitoring', 'C1_sejour_inconnu',
    'Contrôle : relevés rattachés à un séjour absent du dépôt',
    toInt64((SELECT uniqExact((stay_id, ts)) FROM {{ source('bronze', 'monitoring') }})),
    toInt64((SELECT count() FROM {{ ref('fact_monitoring') }})),
    toInt64((SELECT countIf(reject_reason LIKE '%sejour_inconnu%')
             FROM {{ ref('monitoring_rejets') }})),
    toInt64(0),
    'Sans séjour parent, le service du relevé n''est pas résoluble',
    now()

UNION ALL
-- ── C2 · CONTRÔLE (attendu à zéro) ──────────────────────────────────────────
SELECT
    '{{ run_id }}', 'silver', 'fact_diagnostic', 'C2_sejour_inconnu',
    'Contrôle : diagnostics rattachés à un séjour absent du dépôt',
    -- Lus au grain du fait (séjour, code), celui de la déduplication.
    toInt64((SELECT uniqExact((stay_id, code_cim10)) FROM {{ source('bronze', 'diagnostics') }})),
    toInt64((SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64((SELECT uniqExact((stay_id, code_cim10)) FROM {{ source('bronze', 'diagnostics') }})
          - (SELECT count() FROM {{ ref('fact_diagnostic') }})),
    toInt64(0),
    'Sans séjour parent, le patient du diagnostic n''est pas résoluble',
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
    -- les séjours ouverts seraient signalés deux fois.
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
    'Évalué sur les seuls séjours temporellement cohérents',
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
-- ═══ Couche gold : ce que la diffusion a coûté en masquage de cellules ══════
-- La preuve chiffrée que le k-anonymat n'est pas qu'une intention affichée : une ligne
-- par table diffusée à la recherche, reprise telle quelle de `k_anonymat_controle`.
SELECT
    '{{ run_id }}', 'gold', table_cible, 'RGPD_k_anonymat',
    concat('Cellules masquées — ', motif),
    toInt64(cellules_calculees),
    toInt64(cellules_diffusees),
    toInt64(cellules_masquees),
    toInt64(0),
    'La ligne reste publiée, l''effectif est retiré : le chercheur sait qu''une valeur est protégée',
    now()
FROM {{ ref('k_anonymat_controle') }}

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
