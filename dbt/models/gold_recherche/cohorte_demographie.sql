{{ config(order_by='(code_cim10, sexe, tranche_age_debut)') }}
-- Marge par pathologie, sexe et tranche d'âge.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  Appliquer le seuil séparément sur une vue agrégée et sur sa décomposition
--  NE SUFFIT PAS. Si une seule cellule fine est supprimée, sa valeur se retrouve
--  par soustraction :
--
--      total de la marge − somme des cellules fines diffusées = cellule cachée
--
--  L'attaque ne demande aucun privilège : une jointure entre les deux tables, avec
--  le compte chercheur, suffit à reconstruire pathologie, sexe, tranche d'âge,
--  département **et** effectif exact de patients censés être protégés. C'est le
--  mécanisme dit de « différenciation », bien connu du contrôle statistique de la
--  divulgation.
--
--  Parade appliquée ici : la **suppression complémentaire**. Une marge n'est diffusée
--  que si TOUTE sa décomposition l'est. Dès qu'une cellule fine tombe sous le seuil,
--  la ligne agrégée disparaît elle aussi — il n'y a alors plus rien à soustraire.
--
--  Le coût est assumé et mesuré : quelques lignes agrégées de moins, reportées dans
--  `k_anonymat_controle`. Le principe retenu est qu'une donnée douteuse ne se diffuse
--  pas, même agrégée.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- L'alias de l'agrégat ne reprend pas le nom de la colonne source : sinon le filtre
-- le réinterpréterait comme un agrégat imbriqué.
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
    FROM {{ ref('cellules_demographie') }}
    GROUP BY code_cim10, libelle, sexe, tranche_age_debut, tranche_age
)
WHERE total >= {{ var('seuil_k') }}
  AND cellules_fines_supprimees = 0
