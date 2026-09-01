-- Cloisonnement RGPD au niveau du moteur, pas seulement dans l'outil de dataviz.
--
-- Chaque usage a son propre compte SQL, en lecture seule, limité à SA base gold.
-- Conséquence : même une requête SQL écrite à la main dans Metabase par un
-- utilisateur « recherche » ne peut pas atteindre les données de pilotage — le
-- refus vient de ClickHouse. Les couches bronze, silver et ops ne sont exposées
-- à aucun des deux : elles restent réservées au compte technique du pipeline.
--
-- Script rejoué à chaque `eds provision-warehouse` : entièrement idempotent.

-- `OR REPLACE` et non `IF NOT EXISTS` : sur un compte déjà créé, ce dernier ne
-- ferait rien, et changer le mot de passe dans .env laisserait l'ancien actif.
-- Le provisionnement doit rendre l'entrepôt conforme à sa configuration, pas
-- seulement l'initialiser.

-- ── Garde-fous communs aux deux comptes de restitution ──────────────────────
-- Le GRANT interdit déjà toute écriture : ces bornes ne visent pas
-- l'exfiltration mais la **disponibilité**. Metabase laisse écrire du SQL libre ;
-- une requête maladroite pourrait sinon saturer la mémoire du moteur et priver
-- l'autre usage de son tableau de bord.
--
-- `readonly = 2` et non `1` : le niveau 1 interdirait aussi de changer un
-- paramètre de session, ce que le pilote JDBC de Metabase fait à la connexion.
--
-- `max_memory_usage` est paramétré et non figé : 4 Go conviennent sur un poste,
-- mais la VM cloud n'a que 2 Gio de RAM au total. Une requête libre écrite dans
-- Metabase y tuerait le moteur — et donc le tableau de bord de l'autre usage.
CREATE SETTINGS PROFILE OR REPLACE restitution SETTINGS
    readonly            = 2,
    max_execution_time  = 60,
    max_memory_usage    = {max_memory_usage},
    max_result_rows     = 1000000,
    max_result_bytes    = 200000000,
    result_overflow_mode = 'throw';

-- ── Pilotage hospitalier ────────────────────────────────────────────────────
CREATE USER OR REPLACE chu_pilotage
    IDENTIFIED WITH sha256_password BY '{pilotage_password}'
    DEFAULT DATABASE eds_gold_pilotage
    SETTINGS PROFILE restitution;

GRANT SELECT ON eds_gold_pilotage.* TO chu_pilotage;
REVOKE ALL ON eds_bronze.*         FROM chu_pilotage;
REVOKE ALL ON eds_silver.*         FROM chu_pilotage;
REVOKE ALL ON eds_gold_recherche.* FROM chu_pilotage;
REVOKE ALL ON ops.*                FROM chu_pilotage;

-- ── Recherche clinique ──────────────────────────────────────────────────────
CREATE USER OR REPLACE chu_recherche
    IDENTIFIED WITH sha256_password BY '{recherche_password}'
    DEFAULT DATABASE eds_gold_recherche
    SETTINGS PROFILE restitution;

GRANT SELECT ON eds_gold_recherche.* TO chu_recherche;
REVOKE ALL ON eds_bronze.*        FROM chu_recherche;
REVOKE ALL ON eds_silver.*        FROM chu_recherche;
REVOKE ALL ON eds_gold_pilotage.* FROM chu_recherche;
REVOKE ALL ON ops.*               FROM chu_recherche;

-- ── Quota : borne la consommation sur une heure glissante ───────────────────
-- Créé après les comptes, qu'il référence. Largement au-dessus d'un usage
-- normal de tableau de bord (quelques dizaines de requêtes par heure) : il ne
-- gêne personne et arrête une boucle emballée.
CREATE QUOTA OR REPLACE restitution
    KEYED BY user_name
    FOR INTERVAL 1 HOUR MAX queries = 3000, execution_time = 1800
    TO chu_pilotage, chu_recherche;
