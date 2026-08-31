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


-- ═══════════════════════════════════════════════════════════════════════════
--  Description de cohorte : deux niveaux de détail, et une précaution
--  indispensable entre les deux.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Appliquer `HAVING >= 5` séparément sur une vue agrégée et sur sa
-- décomposition NE SUFFIT PAS. Si une seule cellule fine est supprimée, sa
-- valeur se retrouve par soustraction :
--
--     total de la marge  −  somme des cellules fines diffusées  =  cellule cachée
--
-- L'attaque ne demande aucun privilège particulier : une jointure entre les deux
-- tables, avec le compte chercheur, suffit à reconstruire la pathologie, le sexe,
-- la tranche d'âge, le département **et** l'effectif exact de patients censés
-- être protégés. C'est le mécanisme dit de « différenciation », bien connu du
-- contrôle statistique de la divulgation.
--
-- La parade appliquée ici est la **suppression complémentaire** : une marge
-- n'est diffusée que si TOUTE sa décomposition l'est. Dès qu'une cellule fine
-- tombe sous le seuil, la ligne agrégée correspondante disparaît elle aussi —
-- il n'y a alors plus rien à soustraire.
--
-- Le coût est assumé et mesuré : quelques lignes agrégées de moins, reportées
-- dans `k_anonymat_controle`. Le principe retenu est qu'une donnée douteuse ne
-- se diffuse pas, même agrégée.

-- Grain fin, avec le marqueur de diffusabilité. Sert de base aux deux vues.
-- Elle est construite avec la couche gold, car elle encode une règle de
-- **diffusion** et non une règle de qualité — mais elle est rangée en silver,
-- hors de portée des comptes de restitution.
--
-- ⚠ Cette table vit dans `eds_silver`, PAS dans la base des chercheurs : elle
-- contient les effectifs des cellules sous le seuil, précisément ce que le
-- k-anonymat doit cacher. La placer dans `eds_gold_recherche` exposerait
-- directement ce que la suppression complémentaire protège.
DROP TABLE IF EXISTS eds_gold_recherche.cellules_demographie;

CREATE OR REPLACE TABLE eds_silver.cellules_demographie
ENGINE = MergeTree
ORDER BY (code_cim10, sexe, tranche_age_debut, region_code)
COMMENT 'Travail interne du k-anonymat : grain fin AVEC les effectifs sous le seuil — jamais diffusé'
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
    uniqExact(d.patient_pseudo)                                     AS nb_patients,
    uniqExact(d.patient_pseudo) >= 5                                AS diffusable
FROM eds_silver.fact_diagnostic AS d
INNER JOIN eds_silver.dim_cim10   AS c USING (code_cim10)
INNER JOIN eds_silver.dim_patient AS p USING (patient_pseudo)
GROUP BY code_cim10, libelle, region_code, sexe, tranche_age_debut, tranche_age;

-- ── Grain fin diffusé : les cellules d'au moins 5 patients ──────────────────
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_demographie_region
ENGINE = MergeTree
ORDER BY (code_cim10, region_code, sexe, tranche_age_debut)
COMMENT 'Distribution sexe × âge × département (k >= 5 : cellules trop petites supprimées)'
AS
SELECT code_cim10, libelle, region_code, sexe, tranche_age_debut, tranche_age, nb_patients
FROM eds_silver.cellules_demographie
WHERE diffusable;

-- ── Marge par pathologie, sexe et âge ───────────────────────────────────────
-- Diffusée uniquement si sa décomposition départementale l'est intégralement :
-- c'est la suppression complémentaire décrite en tête de section.
CREATE OR REPLACE TABLE eds_gold_recherche.cohorte_demographie
ENGINE = MergeTree
ORDER BY (code_cim10, sexe, tranche_age_debut)
COMMENT 'Distribution par sexe et tranche d''âge, par pathologie (k >= 5 et suppression complémentaire)'
AS
-- L'alias de l'agrégat ne reprend pas le nom de la colonne source : sinon le
-- `HAVING` le réinterpréterait comme un agrégat imbriqué.
SELECT
    code_cim10,
    libelle,
    sexe,
    tranche_age_debut,
    tranche_age,
    total AS nb_patients
FROM
(
    SELECT
        code_cim10,
        libelle,
        sexe,
        tranche_age_debut,
        tranche_age,
        sum(nb_patients)        AS total,
        countIf(NOT diffusable) AS cellules_fines_supprimees
    FROM eds_silver.cellules_demographie
    GROUP BY code_cim10, libelle, sexe, tranche_age_debut, tranche_age
)
WHERE total >= 5
  AND cellules_fines_supprimees = 0;

-- ── Preuve du dispositif, diffusable ────────────────────────────────────────
-- Exposée volontairement aux chercheurs : elle dit combien de cellules ont été
-- retirées et pourquoi, sans jamais révéler lesquelles ni leur effectif. Depuis
-- la suppression complémentaire, connaître ces nombres n'aide plus à retrouver
-- quoi que ce soit : les marges correspondantes ont disparu elles aussi.
CREATE OR REPLACE TABLE eds_gold_recherche.k_anonymat_controle
ENGINE = MergeTree
ORDER BY table_cible
COMMENT 'Effet du seuil k >= 5 : cellules calculées, diffusées, supprimées, et suppressions complémentaires'
AS
SELECT
    'cohorte_demographie_region' AS table_cible,
    'seuil k >= 5'               AS motif,
    count()                      AS cellules_calculees,
    countIf(diffusable)          AS cellules_diffusees,
    countIf(NOT diffusable)      AS cellules_supprimees,
    5                            AS seuil_k
FROM eds_silver.cellules_demographie

UNION ALL

SELECT
    'cohorte_demographie',
    'suppression complémentaire (décomposition incomplète)',
    uniqExact((code_cim10, sexe, tranche_age_debut)),
    (SELECT count() FROM eds_gold_recherche.cohorte_demographie),
    uniqExact((code_cim10, sexe, tranche_age_debut))
        - (SELECT count() FROM eds_gold_recherche.cohorte_demographie),
    5
FROM eds_silver.cellules_demographie;
