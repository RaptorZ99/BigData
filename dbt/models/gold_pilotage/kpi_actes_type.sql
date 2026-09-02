{{ config(order_by='code_ccam') }}
-- KPI évolution 3 — Répartition des actes par type (code et libellé CCAM).
--
-- Grain : le code CCAM. La part est calculée sur l'ensemble des actes : chaque acte
-- porte un seul code, les parts se somment donc à 100 %.
--
-- Jointure externe vers la nomenclature : un code inconnu du référentiel resterait
-- visible sous son code, avec le libellé « code inconnu », plutôt que de disparaître
-- d'une répartition censée être exhaustive.
WITH (SELECT count() FROM {{ ref('fact_acte') }}) AS total_actes
SELECT
    a.code_ccam                                         AS code_ccam,
    if(c.code_ccam = '', 'code inconnu', c.libelle)     AS libelle,
    c.tarif_euros                                       AS tarif_euros,
    count()                                             AS nb_actes,
    uniqExact(a.stay_id)                                AS nb_sejours,
    round(100.0 * count() / total_actes, 1)             AS part_pct,
    ifNull(sum(a.montant_euros), 0)                     AS montant_facture_euros
FROM {{ ref('fact_acte') }} AS a
LEFT JOIN {{ ref('dim_ccam') }} AS c USING (code_ccam)
GROUP BY code_ccam, libelle, tarif_euros
