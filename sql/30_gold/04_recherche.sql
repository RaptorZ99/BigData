-- Gold recherche — cohortes cliniques.
--
-- Trois garde-fous RGPD s'appliquent à TOUTES les tables de cette base :
--   1. agrégats uniquement — aucune ligne patient n'est exposée ;
--   2. k-anonymat : `HAVING uniqExact(patient_pseudo) >= 5`, appliqué à chaque
--      cellule diffusée (une cellule = une ligne de résultat) ;
--   3. âges diffusés en tranches de 10 ans, jamais en valeur exacte — et
--      calculés depuis l'année de naissance, la date complète n'existant plus
--      nulle part dans l'entrepôt.
--
-- L'âge est celui atteint dans l'année en cours : la généralisation à l'année
-- interdit un calcul au jour près, ce qui est précisément l'effet recherché.

-- ── Taille des cohortes par pathologie ──────────────────────────────────────
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_pathologie
ENGINE = MergeTree
ORDER BY code_cim10
COMMENT 'Taille des cohortes par diagnostic CIM-10 (cohortes de moins de 5 patients non diffusées)'
AS
SELECT
    d.code_cim10                                        AS code_cim10,
    c.libelle                                           AS libelle,
    uniqExact(d.patient_pseudo)                         AS nb_patients,
    uniqExactIf(d.patient_pseudo, d.is_principal)       AS nb_patients_diag_principal,
    uniqExact(d.stay_id)                                AS nb_sejours,
    countIf(d.is_principal)                             AS nb_diagnostics_principaux,
    countIf(NOT d.is_principal)                         AS nb_diagnostics_associes
FROM eds_silver.fact_diagnostic AS d
INNER JOIN eds_silver.dim_cim10 AS c USING (code_cim10)
GROUP BY code_cim10, libelle
HAVING nb_patients >= 5;

-- ── Prévalence par pathologie ───────────────────────────────────────────────
-- Dénominateur : patients distincts ayant au moins un séjour. Il est calculé
-- comme un scalaire agrégé, jamais par jointure entre deux tables de faits.
CREATE OR REPLACE TABLE eds_gold_recherche.prevalence_pathologie
ENGINE = MergeTree
ORDER BY code_cim10
COMMENT 'Prévalence : part des patients concernés par chaque pathologie'
AS
WITH (SELECT uniqExact(patient_pseudo) FROM eds_silver.fact_sejour) AS total_patients
SELECT
    d.code_cim10                                                       AS code_cim10,
    c.libelle                                                          AS libelle,
    uniqExact(d.patient_pseudo)                                        AS nb_patients,
    total_patients                                                     AS nb_patients_total,
    round(100.0 * uniqExact(d.patient_pseudo) / total_patients, 2)     AS prevalence_pct
FROM eds_silver.fact_diagnostic AS d
INNER JOIN eds_silver.dim_cim10 AS c USING (code_cim10)
GROUP BY code_cim10, libelle
HAVING nb_patients >= 5;

-- ── Pyramide des âges de l'ensemble de la population suivie ─────────────────
-- Grain : sexe × tranche d'âge, un patient compté UNE fois.
--
-- Cette table existe précisément parce que `nb_patients` est une mesure **non
-- additive** : la sommer à travers les pathologies compterait cinq fois un
-- patient portant cinq diagnostics. La distribution d'ensemble doit donc être
-- calculée à son propre grain, jamais dérivée de `cohorte_demographie`.
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_demographie_globale
ENGINE = MergeTree
ORDER BY (sexe, tranche_age_debut)
COMMENT 'Distribution de la population suivie par sexe et tranche d''âge (patients distincts)'
AS
SELECT
    p.sex                                                           AS sexe,
    intDiv(toYear(today()) - p.birth_year, 10) * 10                 AS tranche_age_debut,
    concat(
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10),
        '-',
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10 + 9)
    )                                                               AS tranche_age,
    uniqExact(s.patient_pseudo)                                     AS nb_patients
FROM eds_silver.fact_sejour AS s
INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
GROUP BY sexe, tranche_age_debut, tranche_age
HAVING nb_patients >= 5;

-- ── Description de cohorte : âge et sexe, par pathologie ────────────────────
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_demographie
ENGINE = MergeTree
ORDER BY (code_cim10, sexe, tranche_age_debut)
COMMENT 'Distribution par sexe et tranche d''âge, par pathologie (k >= 5 par cellule)'
AS
SELECT
    d.code_cim10                                                    AS code_cim10,
    c.libelle                                                       AS libelle,
    p.sex                                                           AS sexe,
    intDiv(toYear(today()) - p.birth_year, 10) * 10                 AS tranche_age_debut,
    concat(
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10),
        '-',
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10 + 9)
    )                                                               AS tranche_age,
    uniqExact(d.patient_pseudo)                                     AS nb_patients
FROM eds_silver.fact_diagnostic AS d
INNER JOIN eds_silver.dim_cim10  AS c USING (code_cim10)
INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
GROUP BY code_cim10, libelle, sexe, tranche_age_debut, tranche_age
HAVING nb_patients >= 5;

-- ── Description de cohorte au grain fin (avec le département) ───────────────
-- C'est à ce niveau de détail que le k-anonymat mord réellement : certaines
-- cellules descendent sous 5 patients et sont supprimées de la diffusion.
-- Le nombre de cellules ainsi retirées est reporté dans le rapport qualité.
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_demographie_region
ENGINE = MergeTree
ORDER BY (code_cim10, region_code, sexe, tranche_age_debut)
COMMENT 'Distribution sexe × âge × département (k >= 5 : cellules trop petites supprimées)'
AS
SELECT
    d.code_cim10                                                    AS code_cim10,
    c.libelle                                                       AS libelle,
    p.region_code                                                   AS region_code,
    p.sex                                                           AS sexe,
    intDiv(toYear(today()) - p.birth_year, 10) * 10                 AS tranche_age_debut,
    concat(
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10),
        '-',
        toString(intDiv(toYear(today()) - p.birth_year, 10) * 10 + 9)
    )                                                               AS tranche_age,
    uniqExact(d.patient_pseudo)                                     AS nb_patients
FROM eds_silver.fact_diagnostic AS d
INNER JOIN eds_silver.dim_cim10   AS c USING (code_cim10)
INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
GROUP BY code_cim10, libelle, region_code, sexe, tranche_age_debut, tranche_age
HAVING nb_patients >= 5;

-- ── Preuve du k-anonymat, diffusable ────────────────────────────────────────
-- Table volontairement exposée aux chercheurs : elle indique combien de
-- cellules ont été retirées, sans jamais révéler lesquelles ni leur effectif.
CREATE OR REPLACE TABLE eds_gold_recherche.k_anonymat_controle
ENGINE = MergeTree
ORDER BY table_cible
COMMENT 'Effet du seuil k >= 5 : nombre de cellules calculées, diffusées et supprimées'
AS
-- Les cellules « calculées » doivent l'être sur exactement le même périmètre que
-- les cellules diffusées, jointure au référentiel CIM-10 comprise : sans cela,
-- un code orphelin serait imputé au seuil k = 5 alors qu'il aurait été écarté
-- pour une tout autre raison, et le compteur mélangerait deux causes.
WITH cellules_brutes AS
(
    SELECT count() AS n
    FROM
    (
        SELECT d.code_cim10, p.region_code, p.sex,
               intDiv(toYear(today()) - p.birth_year, 10) AS tranche
        FROM eds_silver.fact_diagnostic AS d
        INNER JOIN eds_silver.dim_cim10   AS c USING (code_cim10)
        INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
        GROUP BY d.code_cim10, p.region_code, p.sex, tranche
    )
)
SELECT
    'cohorte_demographie_region'                                        AS table_cible,
    (SELECT n FROM cellules_brutes)                                     AS cellules_calculees,
    (SELECT count() FROM eds_gold_recherche.cohorte_demographie_region) AS cellules_diffusees,
    (SELECT n FROM cellules_brutes)
        - (SELECT count() FROM eds_gold_recherche.cohorte_demographie_region) AS cellules_supprimees,
    5                                                                   AS seuil_k;
