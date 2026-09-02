{{ config(order_by='(code_cim10, tranche_age_debut, sexe)') }}
-- KPI 6 — Description de cohorte : distribution par âge et sexe, pour chaque
-- pathologie.
--
-- Grain : pathologie × tranche d'âge × sexe.
--
-- Restreint au **diagnostic principal**, c'est-à-dire au motif de l'hospitalisation.
-- Décrire une cohorte, c'est décrire les patients pris en charge POUR cette
-- pathologie ; y inclure ceux qui la portent en comorbidité mélangerait deux
-- populations et gonflerait les cohortes chroniques (diabète, insuffisance cardiaque)
-- de plus du double. La prévalence, elle, compte bien tous les rangs : les deux
-- tables répondent à deux questions distinctes, et c'est voulu.
--
-- Âges diffusés en tranches de dix ans, jamais en valeur exacte, et calculés depuis
-- la seule année de naissance : la date complète n'existe nulle part dans l'entrepôt.
--
-- k-anonymat : une cellule de moins de `seuil_k` patients garde sa ligne, mais son
-- effectif est masqué (même principe qu'en tête de `prevalence_pathologie`).
--
-- Le test `assert_pas_de_suppression_partielle` vérifie qu'aucune pathologie n'est
-- publiée à moitié : sans cela, sommer les cellules d'une pathologie pour en tirer
-- une répartition par sexe donnerait un ratio biaisé, les cellules manquantes étant
-- systématiquement les plus petites.
SELECT
    code_cim10,
    libelle,
    tranche_age_debut,
    tranche_age,
    sexe,
    nb >= {{ var('seuil_k') }}  AS diffusable,
    if(diffusable, nb, NULL)    AS nb_patients
FROM
(
    SELECT
        d.code_cim10                                AS code_cim10,
        c.libelle                                   AS libelle,
        {{ tranche_age_debut('p.birth_year') }}     AS tranche_age_debut,
        {{ tranche_age_libelle('p.birth_year') }}   AS tranche_age,
        p.sex                                       AS sexe,
        uniqExact(d.patient_pseudo)                 AS nb
    FROM {{ ref('fact_diagnostic') }} AS d
    INNER JOIN {{ ref('dim_cim10') }}   AS c USING (code_cim10)
    INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
    WHERE d.is_principal
    GROUP BY code_cim10, libelle, tranche_age_debut, tranche_age, sexe
)
