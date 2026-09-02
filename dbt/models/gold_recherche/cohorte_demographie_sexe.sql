{{ config(order_by='(code_cim10, sexe)') }}
-- Répartition par sexe de chaque cohorte, au grain pathologie × sexe.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  Pourquoi une table de plus, alors que `cohorte_demographie` porte déjà le sexe ?
--
--  Parce qu'y sommer les tranches d'âge donne un résultat FAUX. Cette table-là est
--  filtrée par le seuil et par la suppression complémentaire : les cellules absentes
--  ne manquent pas au hasard, ce sont systématiquement les plus petites. Un ratio
--  calculé sur ce qu'il en reste est biaisé — mesuré à neuf points sur les infections
--  urinaires (71,5 % de femmes au lieu de 62,5 %).
--
--  C'est le même principe que pour la pyramide des âges : une mesure se calcule à son
--  propre grain, jamais sur les restes d'un autre.
--
--  La suppression complémentaire s'applique ici aussi, et pour la raison exposée en
--  §7.2 du rapport : `cohorte_pathologie` diffuse l'effectif total de la pathologie.
--  Publier la seule cellule des hommes livrerait celle des femmes par soustraction.
--  Une pathologie n'est donc présente que si TOUTES ses cellules de sexe atteignent
--  le seuil.
-- ═══════════════════════════════════════════════════════════════════════════
WITH cellules AS (
    SELECT
        d.code_cim10                AS code_cim10,
        c.libelle                   AS libelle,
        p.sex                       AS sexe,
        uniqExact(d.patient_pseudo) AS nb
    FROM {{ ref('fact_diagnostic') }} AS d
    INNER JOIN {{ ref('dim_cim10') }}   AS c USING (code_cim10)
    INNER JOIN {{ ref('dim_patient') }} AS p USING (patient_pseudo)
    GROUP BY code_cim10, libelle, sexe
)
SELECT
    code_cim10,
    libelle,
    sexe,
    nb AS nb_patients
FROM
(
    SELECT *, min(nb) OVER (PARTITION BY code_cim10) AS plus_petite_cellule
    FROM cellules
)
WHERE plus_petite_cellule >= {{ var('seuil_k') }}
