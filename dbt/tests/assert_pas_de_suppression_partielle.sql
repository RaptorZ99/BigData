-- Une pathologie ne doit jamais être publiée à moitié.
--
-- Si certaines cellules d'une pathologie sont diffusées et d'autres masquées, deux
-- choses cassent d'un coup :
--
--   * l'agrégation devient FAUSSE — sommer les cellules restantes pour en tirer une
--     répartition par sexe ou une pyramide donne un ratio biaisé, puisque les cellules
--     manquantes ne manquent pas au hasard : ce sont systématiquement les plus petites ;
--   * la protection devient POREUSE — si un total de la pathologie est diffusé
--     ailleurs, la valeur masquée se retrouve par soustraction (attaque dite « par
--     différenciation »).
--
-- Sur le jeu de données courant, les trois pathologies sous le seuil le sont sur
-- TOUTES leurs cellules : la condition tient d'elle-même. Ce test est là pour que le
-- jour où elle cesserait de tenir, on l'apprenne par un échec de build et non par une
-- courbe fausse sur un tableau de bord.
SELECT
    code_cim10,
    countIf(diffusable)     AS cellules_diffusees,
    countIf(NOT diffusable) AS cellules_masquees
FROM {{ ref('cohorte_demographie') }}
GROUP BY code_cim10
HAVING cellules_diffusees > 0 AND cellules_masquees > 0
