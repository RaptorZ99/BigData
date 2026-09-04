{{ config(order_by='rang') }}
-- KPI évolution 3 — Nombre d'actes par type d'acte (code et libellé CCAM).
--
-- Grain : le code CCAM. Chaque acte porte un seul code : la somme des lignes vaut le
-- nombre d'actes, ce que vérifie `assert_actes_reconcilies`.
--
-- Jointure externe vers la nomenclature : un code inconnu du référentiel resterait
-- visible sous son code, avec le libellé « code inconnu », plutôt que de disparaître
-- d'une répartition censée être exhaustive.
--
-- `rang` classe les types du plus fréquent au plus rare ; clé de tri physique de la table.
SELECT
    code_ccam,
    libelle_ccam,
    nb_actes,
    row_number() OVER (ORDER BY nb_actes DESC, code_ccam) AS rang
FROM
(
    SELECT
        a.code_ccam                                         AS code_ccam,
        if(c.code_ccam = '', 'code inconnu', c.libelle)     AS libelle_ccam,
        count()                                             AS nb_actes
    FROM {{ ref('fact_acte') }} AS a
    LEFT JOIN {{ ref('dim_ccam') }} AS c USING (code_ccam)
    GROUP BY code_ccam, libelle_ccam
)
