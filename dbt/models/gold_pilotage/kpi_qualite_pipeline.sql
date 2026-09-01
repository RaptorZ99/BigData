{{ config(order_by='rule') }}
-- Le rapport qualité, exposé aux utilisateurs métier.
--
-- Rendre visible ce qui a été écarté et pourquoi, c'est ce qui permet de répondre à
-- « d'où sort ce chiffre ? » depuis le tableau de bord lui-même, sans ouvrir la base
-- d'exploitation — à laquelle le compte pilotage n'a pas accès.
--
-- Ce modèle référence `quality_report` : le graphe garantit donc qu'il s'exécute après
-- lui, y compris après les contrôles RGPD de la couche gold. Dans la version SQL, cet
-- ordre reposait sur une règle écrite à la main dans les conventions du projet.
SELECT
    q.layer         AS couche,
    q.table_name    AS table_cible,
    q.rule          AS rule,
    q.rule_label    AS controle,
    -- Nature de la règle : ce qu'il faut lire dans les compteurs. Libellés courts —
    -- la colonne du tableau de bord tronquait « contrôle conforme ».
    multiIf(
        q.rows_rejected > 0, 'rejet',
        q.rows_flagged  > 0, 'signalement',
        'conforme'
    )               AS nature,
    q.rows_in       AS lignes_lues,
    q.rows_kept     AS lignes_conservees,
    q.rows_rejected AS lignes_ecartees,
    q.rows_flagged  AS lignes_signalees,
    q.details       AS precisions,
    q.checked_at    AS controle_le
FROM {{ ref('quality_report') }} AS q
WHERE q.run_id = '{{ var("run_id") }}'
